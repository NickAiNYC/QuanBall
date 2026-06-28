"""
scanner.py — Main scanner loop.

Ties everything together:
    1. Fetch sports events from Gamma API
    2. Fetch order books for all markets (parallel)
    3. Run detectors on each event
    4. Filter opportunities through risk gate
    5. Execute via Executor
    6. Track positions and exposure
    7. Send alerts

Run with:
    python -m scanner   (uses default config + env vars)
    python -m scanner --config /path/to/config.yaml
    python -m scanner --dry-run   (no real orders)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import time
from typing import List, Optional

from config import Config, load_config
from gamma_client import GammaClient
from clob_client import CLOBRestClient, CLOBWSClient, CLOBOrderClient
from detectors import scan_event_for_opportunities
from executor import Executor
from risk import (
    Blacklist, ExposureTracker, PnLTracker, risk_gate,
)
from alerts import AlertSender
from models import Event, Market, Opportunity, Sport

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Logging setup
# ─────────────────────────────────────────────────────────────────────────────

def setup_logging(cfg: Config, level: str = "INFO"):
    import os
    os.makedirs(os.path.dirname(cfg.log_path), exist_ok=True)
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=getattr(logging, level),
        format=fmt,
        handlers=[
            logging.FileHandler(cfg.log_path),
            logging.StreamHandler(sys.stdout),
        ],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Scanner
# ─────────────────────────────────────────────────────────────────────────────

class Scanner:
    """Main scanner orchestrator."""

    def __init__(
        self,
        cfg: Config,
        dry_run: bool = True,
        sports_filter: Optional[List[Sport]] = None,
    ):
        self.cfg = cfg
        self.dry_run = dry_run
        self.sports_filter = sports_filter or [Sport.NBA]  # default NBA per article

        # State
        self.tracker = ExposureTracker()
        self.pnl = PnLTracker()
        self.blacklist = Blacklist(os.path.join(os.path.dirname(cfg.db_path), "blacklist.json"))

        # Clients (initialized in start())
        self.gamma: Optional[GammaClient] = None
        self.rest_clob: Optional[CLOBRestClient] = None
        self.ws_clob: Optional[CLOBWSClient] = None
        self.order_client: Optional[CLOBOrderClient] = None
        self.executor: Optional[Executor] = None
        self.alerts: Optional[AlertSender] = None

        self._running = False

    async def start(self):
        """Initialize all clients."""
        self.gamma = GammaClient(self.cfg)
        await self.gamma.__aenter__()

        self.rest_clob = CLOBRestClient(self.cfg)
        await self.rest_clob.__aenter__()

        if not self.dry_run:
            try:
                self.order_client = CLOBOrderClient(self.cfg)
                self.order_client._ensure_client()
                log.info("Authenticated CLOB order client initialized")
            except Exception as e:
                log.error(f"Failed to init order client: {e}; falling back to dry-run")
                self.dry_run = True

        self.executor = Executor(
            self.cfg,
            order_client=self.order_client,
            rest_client=self.rest_clob,
        )

        self.alerts = AlertSender(self.cfg)
        log.info(f"Scanner started (dry_run={self.dry_run})")

    async def stop(self):
        """Clean up clients."""
        if self.gamma:
            await self.gamma.__aexit__(None, None, None)
        if self.rest_clob:
            await self.rest_clob.__aexit__(None, None, None)
        if self.ws_clob:
            await self.ws_clob.stop()
        if self.alerts:
            await self.alerts.client.aclose()
        log.info("Scanner stopped")

    # ───────────────────────────────────────────────────────────────────────
    # Main scan loop
    # ───────────────────────────────────────────────────────────────────────

    async def scan_once(self) -> List[Opportunity]:
        """One full scan cycle. Returns all opportunities found."""
        # 1. Fetch sports events
        events = await self.gamma.fetch_sports_events_with_markets(
            sports=self.sports_filter,
            max_events=50,
        )
        log.info(f"Fetched {len(events)} sports events")

        # 2. Filter to events resolving soon (sports = daily cadence)
        now = time.time()
        fresh_events = []
        for ev in events:
            if not ev.markets:
                continue
            # Filter: at least one market resolves within next 12h
            cutoff = now + self.cfg.scanner.resolve_within_hours * 3600
            ev_has_fresh = False
            for m in ev.markets:
                if m.end_date:
                    try:
                        # end_date may be ISO string or datetime
                        end_ts = m.end_date
                        if isinstance(end_ts, str):
                            from datetime import datetime
                            end_ts = datetime.fromisoformat(end_ts.replace("Z", "+00:00")).timestamp()
                        if now <= end_ts <= cutoff:
                            ev_has_fresh = True
                            break
                    except Exception:
                        pass
                else:
                    # No end date — assume fresh
                    ev_has_fresh = True
                    break
            if ev_has_fresh:
                fresh_events.append(ev)

        log.info(f"{len(fresh_events)} events resolve within window")

        # 3. Fetch all order books in parallel
        all_markets = [m for ev in fresh_events for m in ev.markets]
        books = await self.rest_clob.get_books_for_markets(all_markets, concurrency=16)

        # Attach books to markets
        for ev in fresh_events:
            for m in ev.markets:
                if m.condition_id in books:
                    m.book = books[m.condition_id]
                    m.last_update_ts = time.time()

        # 4. Run detectors per event
        all_opps: List[Opportunity] = []
        for ev in fresh_events:
            try:
                opps = scan_event_for_opportunities(ev, self.cfg)
                all_opps.extend(opps)
            except Exception as e:
                log.warning(f"Error scanning event {ev.slug}: {e}")

        log.info(f"Detected {len(all_opps)} raw opportunities")

        # 5. Sort by edge and filter duplicates
        all_opps.sort(key=lambda o: o.net_edge_bps, reverse=True)
        seen_markets = set()
        deduped = []
        for opp in all_opps:
            # Skip if any leg's market is already in a higher-edge opp
            key = frozenset(l.market.condition_id for l in opp.legs)
            if key in seen_markets:
                continue
            seen_markets.add(key)
            deduped.append(opp)

        return deduped

    async def run_forever(self):
        """Main loop: scan → gate → execute → repeat."""
        self._running = True

        # Graceful shutdown
        def _signal_handler(sig, frame):
            log.info("Shutdown signal received")
            self._running = False

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        while self._running:
            try:
                opps = await self.scan_once()

                for opp in opps:
                    if not self._running:
                        break

                    # Alert on detection
                    await self.alerts.send_opportunity_alert(opp)

                    # Risk gate
                    check = risk_gate(opp, self.tracker, self.blacklist, self.cfg)
                    if not check.passed:
                        log.info(f"Skipping opp {opp.id}: {check.reason}")
                        continue

                    # Execute
                    log.info(
                        f"Executing opp {opp.id}: type={opp.type.value} "
                        f"edge={opp.net_edge_bps:.0f}bps cost=${opp.total_cost:.2f}"
                    )
                    position, results = await self.executor.execute_opportunity(
                        opp, adjusted_size_usdc=check.adjusted_size_usdc,
                    )

                    # Update tracker
                    if position.status.value == "FILLED":
                        self.tracker.add(opp)

                    # Alert on fill
                    await self.alerts.send_fill_alert(position)

                # Sleep until next scan
                log.info(f"Scan complete; sleeping {self.cfg.scanner.poll_interval_sec}s")
                await asyncio.sleep(self.cfg.scanner.poll_interval_sec)

            except Exception as e:
                log.error(f"Scan cycle error: {e}", exc_info=True)
                await self.alerts.send_error_alert(str(e), context="scan_cycle")
                await asyncio.sleep(5.0)

        await self.stop()


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

import os  # for path joining inside main

async def main():
    parser = argparse.ArgumentParser(description="Polymarket sports arb scanner")
    parser.add_argument("--config", type=str, help="Path to YAML config file")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Don't place real orders (default: true)")
    parser.add_argument("--live", action="store_true",
                        help="Place real orders (requires API keys)")
    parser.add_argument("--sports", type=str, default="NBA",
                        help="Comma-separated sport filter (default: NBA)")
    parser.add_argument("--log-level", type=str, default="INFO")
    parser.add_argument("--once", action="store_true",
                        help="Run one scan cycle and exit")
    args = parser.parse_args()

    cfg = load_config(yaml_path=args.config)
    setup_logging(cfg, args.log_level)

    sports = [Sport(s.strip().upper()) for s in args.sports.split(",")]
    dry_run = not args.live  # --live disables dry run

    scanner = Scanner(cfg, dry_run=dry_run, sports_filter=sports)
    await scanner.start()

    if args.once:
        opps = await scanner.scan_once()
        print(f"\nFound {len(opps)} opportunities:")
        for o in opps[:20]:
            print(f"  {o.type.value:20s} edge={o.net_edge_bps:6.0f}bps  "
                  f"cost=${o.total_cost:7.2f}  profit=${o.net_edge:6.2f}  "
                  f"event={o.event_slug}")
        await scanner.stop()
    else:
        await scanner.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
