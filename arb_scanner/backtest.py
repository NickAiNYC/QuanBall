"""
backtest.py — Historical backtesting framework.

Loads snapshots of order books (saved by the live scanner or pulled from
Polymarket's price history API) and simulates execution to estimate
strategy performance.

Metrics:
    - Total realized PnL
    - Sharpe ratio (per-opportunity)
    - Max drawdown
    - Win rate
    - Average edge captured
    - Slippage-adjusted vs theoretical edge

Usage:
    python -m backtest --snapshots ./data/snapshots --bankroll 50000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from config import Config, load_config, taker_fee_rate, maker_fee_rate
from models import (
    Event, Leg, Market, MarketCategory, MarketType, Opportunity,
    OpportunityType, OrderBook, OrderBookLevel, Position, Sport,
)
from detectors import (
    detect_single_market_arb, detect_negrisk_rebalance_arb,
    detect_combinatorial_arb, scan_event_for_opportunities,
)
from risk import conservative_kelly_size, estimate_slippage_bps

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot loading
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Snapshot:
    """One point-in-time capture of market state."""
    timestamp: float
    events: List[Event] = field(default_factory=list)


def load_snapshots(snapshot_dir: str) -> List[Snapshot]:
    """Load all JSON snapshots from a directory, sorted by timestamp.

    Each snapshot file format:
        {
            "timestamp": 1234567890.0,
            "events": [
                {
                    "slug": "...",
                    "title": "...",
                    "sport": "NBA",
                    "markets": [
                        {
                            "condition_id": "...",
                            "question": "...",
                            "token_id_yes": "...",
                            "token_id_no": "...",
                            "book": {"bids": [...], "asks": [...]},
                            "end_date": "...",
                            "category": "MONEYLINE",
                            "spread_value": -3.5
                        }
                    ]
                }
            ]
        }
    """
    snapshots = []
    if not os.path.isdir(snapshot_dir):
        log.warning(f"Snapshot directory not found: {snapshot_dir}")
        return snapshots

    files = sorted(f for f in os.listdir(snapshot_dir) if f.endswith(".json"))
    for fname in files:
        path = os.path.join(snapshot_dir, fname)
        try:
            with open(path) as f:
                data = json.load(f)
            snap = _parse_snapshot(data)
            snapshots.append(snap)
        except Exception as e:
            log.warning(f"Failed to load snapshot {fname}: {e}")

    snapshots.sort(key=lambda s: s.timestamp)
    log.info(f"Loaded {len(snapshots)} snapshots from {snapshot_dir}")
    return snapshots


def _parse_snapshot(data: Dict) -> Snapshot:
    """Parse a snapshot JSON into Snapshot object."""
    ts = float(data.get("timestamp", time.time()))
    events = []
    for ev_raw in data.get("events", []):
        markets = []
        for m_raw in ev_raw.get("markets", []):
            book_raw = m_raw.get("book", {})
            book = OrderBook(
                bids=[OrderBookLevel(p=float(l["price"]), s=float(l["size"]))
                      for l in book_raw.get("bids", [])],
                asks=[OrderBookLevel(p=float(l["price"]), s=float(l["size"]))
                      for l in book_raw.get("asks", [])],
                timestamp=ts,
            )
            try:
                sport = Sport(m_raw.get("sport", "OTHER"))
            except ValueError:
                sport = Sport.OTHER
            try:
                category = MarketCategory(m_raw.get("category", "OTHER"))
            except ValueError:
                category = MarketCategory.OTHER

            m = Market(
                condition_id=m_raw["condition_id"],
                question=m_raw.get("question", ""),
                slug=m_raw.get("slug", ""),
                event_slug=ev_raw.get("slug", ""),
                token_id_yes=m_raw.get("token_id_yes", ""),
                token_id_no=m_raw.get("token_id_no", ""),
                market_type=MarketType.BINARY,
                sport=sport,
                category=category,
                end_date=m_raw.get("end_date"),
                spread_value=m_raw.get("spread_value"),
                total_value=m_raw.get("total_value"),
                book=book,
                last_update_ts=ts,
            )
            markets.append(m)

        try:
            sport = Sport(ev_raw.get("sport", "OTHER"))
        except ValueError:
            sport = Sport.OTHER

        events.append(Event(
            slug=ev_raw.get("slug", ""),
            title=ev_raw.get("title", ""),
            sport=sport,
            start_time=ev_raw.get("start_time"),
            markets=markets,
        ))

    return Snapshot(timestamp=ts, events=events)


# ─────────────────────────────────────────────────────────────────────────────
# Simulated execution
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SimulatedFill:
    """Result of a simulated order fill."""
    requested_shares: float
    filled_shares: float
    avg_fill_price: float
    slippage_bps: float


def simulate_fill(
    book: OrderBook,
    side: str,        # "BUY" or "SELL"
    target_shares: float,
    is_maker: bool = False,
) -> SimulatedFill:
    """Simulate filling an order against the book.

    For taker orders: walk the book, compute VWAP, apply 0.75% fee.
    For maker orders: assume fill at mid (optimistic) or rest at limit (specified).
    """
    if not book or target_shares <= 0:
        return SimulatedFill(0, 0, 0, 0)

    if is_maker:
        # Maker: assume fill at mid price (best case)
        mid = book.mid or 0.5
        return SimulatedFill(
            requested_shares=target_shares,
            filled_shares=target_shares,
            avg_fill_price=mid,
            slippage_bps=0,
        )

    # Taker: walk the book
    if side == "BUY":
        # Walk asks
        levels = book.asks
    else:
        # Walk bids (reversed)
        levels = sorted(book.bids, key=lambda l: l.price)

    remaining = target_shares
    total_cost = 0.0
    for level in levels:
        take = min(remaining, level.size)
        total_cost += take * level.price
        remaining -= take
        if remaining <= 0:
            break

    filled = target_shares - remaining
    if filled <= 0:
        return SimulatedFill(target_shares, 0, 0, 0)

    avg_price = total_cost / filled
    best_price = levels[0].price if levels else 0
    slippage_bps = ((avg_price - best_price) / best_price * 10_000) if best_price > 0 else 0

    return SimulatedFill(
        requested_shares=target_shares,
        filled_shares=filled,
        avg_fill_price=avg_price,
        slippage_bps=slippage_bps,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Backtest engine
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BacktestResult:
    n_snapshots: int = 0
    n_opportunities: int = 0
    n_executed: int = 0
    n_passed: int = 0
    n_failed: int = 0
    total_pnl_usdc: float = 0.0
    total_cost_usdc: float = 0.0
    realized_pnl_usdc: float = 0.0
    max_drawdown_usdc: float = 0.0
    peak_pnl_usdc: float = 0.0
    edge_history_bps: List[float] = field(default_factory=list)
    slippage_history_bps: List[float] = field(default_factory=list)
    by_type: Dict[str, Dict] = field(default_factory=dict)

    @property
    def win_rate(self) -> float:
        return self.n_passed / self.n_executed if self.n_executed > 0 else 0

    @property
    def avg_edge_bps(self) -> float:
        return sum(self.edge_history_bps) / len(self.edge_history_bps) if self.edge_history_bps else 0

    @property
    def avg_slippage_bps(self) -> float:
        return (sum(self.slippage_history_bps) / len(self.slippage_history_bps)
                if self.slippage_history_bps else 0)

    @property
    def roi_pct(self) -> float:
        return (self.realized_pnl_usdc / self.total_cost_usdc * 100
                if self.total_cost_usdc > 0 else 0)

    def to_dict(self) -> Dict:
        return {
            "n_snapshots": self.n_snapshots,
            "n_opportunities": self.n_opportunities,
            "n_executed": self.n_executed,
            "win_rate": self.win_rate,
            "realized_pnl_usdc": self.realized_pnl_usdc,
            "total_cost_usdc": self.total_cost_usdc,
            "roi_pct": self.roi_pct,
            "avg_edge_bps": self.avg_edge_bps,
            "avg_slippage_bps": self.avg_slippage_bps,
            "max_drawdown_usdc": self.max_drawdown_usdc,
            "by_type": self.by_type,
        }


def run_backtest(
    snapshots: List[Snapshot],
    cfg: Config,
    bankroll_usdc: float = 50_000,
    sports_filter: Optional[List[Sport]] = None,
) -> BacktestResult:
    """Run backtest over a series of snapshots.

    Each snapshot is treated as one "scan cycle". We:
        1. Run detectors on each event in the snapshot
        2. For each detected opportunity, simulate execution with slippage
        3. Track PnL assuming the outcome resolves favorably (for arbs, always)
    """
    result = BacktestResult()
    result.n_snapshots = len(snapshots)
    current_bankroll = bankroll_usdc

    sports_set = set(sports_filter) if sports_filter else None

    for snap in snapshots:
        for event in snap.events:
            if sports_set and event.sport not in sports_set:
                continue

            # Run detectors
            opps = scan_event_for_opportunities(event, cfg)

            for opp in opps:
                result.n_opportunities += 1

                # Simulate execution
                total_filled_cost = 0.0
                all_filled = True
                slippages = []

                for leg in opp.legs:
                    sim = simulate_fill(
                        book=leg.market.book,
                        side="BUY",
                        target_shares=leg.shares,
                        is_maker=leg.is_maker,
                    )
                    if sim.filled_shares < leg.shares * 0.95:
                        all_filled = False
                        break
                    total_filled_cost += sim.filled_shares * sim.avg_fill_price
                    slippages.append(sim.slippage_bps)

                if not all_filled:
                    result.n_failed += 1
                    continue

                # Compute actual PnL with fees + slippage
                fee = total_filled_cost * (maker_fee_rate() if all(l.is_maker for l in opp.legs)
                                          else taker_fee_rate())
                net_cost = total_filled_cost + fee
                payout = opp.guaranteed_payout  # for arbs, guaranteed
                realized = payout - net_cost

                if realized > 0:
                    result.n_passed += 1
                else:
                    result.n_failed += 1
                result.n_executed += 1

                result.realized_pnl_usdc += realized
                result.total_cost_usdc += net_cost
                result.edge_history_bps.append(opp.net_edge_bps)
                if slippages:
                    result.slippage_history_bps.append(sum(slippages) / len(slippages))

                # Track by type
                type_key = opp.type.value
                if type_key not in result.by_type:
                    result.by_type[type_key] = {"n": 0, "pnl": 0.0, "cost": 0.0}
                result.by_type[type_key]["n"] += 1
                result.by_type[type_key]["pnl"] += realized
                result.by_type[type_key]["cost"] += net_cost

                # Track drawdown
                if result.realized_pnl_usdc > result.peak_pnl_usdc:
                    result.peak_pnl_usdc = result.realized_pnl_usdc
                drawdown = result.peak_pnl_usdc - result.realized_pnl_usdc
                if drawdown > result.max_drawdown_usdc:
                    result.max_drawdown_usdc = drawdown

                current_bankroll += realized

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot recorder (for capturing live data for backtesting)
# ─────────────────────────────────────────────────────────────────────────────

async def record_snapshots(
    cfg: Config,
    duration_sec: int = 3600,
    interval_sec: int = 30,
    out_dir: str = "data/snapshots",
):
    """Record live snapshots for later backtesting.

    Run this in parallel with the live scanner to build a historical dataset.
    """
    os.makedirs(out_dir, exist_ok=True)
    gamma = GammaClient(cfg)
    rest = CLOBRestClient(cfg)
    await gamma.__aenter__()
    await rest.__aenter__()

    try:
        start = time.time()
        n = 0
        while time.time() - start < duration_sec:
            try:
                events = await gamma.fetch_sports_events_with_markets(max_events=30)
                all_markets = [m for ev in events for m in ev.markets]
                books = await rest.get_books_for_markets(all_markets, concurrency=16)

                # Attach books and serialize
                snap_data = {
                    "timestamp": time.time(),
                    "events": [],
                }
                for ev in events:
                    ev_data = {
                        "slug": ev.slug,
                        "title": ev.title,
                        "sport": ev.sport.value,
                        "start_time": ev.start_time,
                        "markets": [],
                    }
                    for m in ev.markets:
                        if m.condition_id not in books:
                            continue
                        m.book = books[m.condition_id]
                        ev_data["markets"].append({
                            "condition_id": m.condition_id,
                            "question": m.question,
                            "token_id_yes": m.token_id_yes,
                            "token_id_no": m.token_id_no,
                            "category": m.category.value,
                            "sport": m.sport.value,
                            "end_date": m.end_date,
                            "spread_value": m.spread_value,
                            "total_value": m.total_value,
                            "book": {
                                "bids": [{"price": l.price, "size": l.size}
                                         for l in m.book.bids[:10]],
                                "asks": [{"price": l.price, "size": l.size}
                                         for l in m.book.asks[:10]],
                            },
                        })
                    if ev_data["markets"]:
                        snap_data["events"].append(ev_data)

                fname = os.path.join(out_dir, f"snap_{int(snap_data['timestamp'])}.json")
                with open(fname, "w") as f:
                    json.dump(snap_data, f)
                n += 1
                if n % 10 == 0:
                    log.info(f"Recorded {n} snapshots")

            except Exception as e:
                log.warning(f"Snapshot record error: {e}")

            await asyncio.sleep(interval_sec)
    finally:
        await gamma.__aexit__(None, None, None)
        await rest.__aexit__(None, None, None)

    log.info(f"Snapshot recording complete: {n} snapshots saved to {out_dir}")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Backtest the arb scanner")
    parser.add_argument("--snapshots", type=str, required=True,
                        help="Directory containing snapshot JSONs")
    parser.add_argument("--bankroll", type=float, default=50_000)
    parser.add_argument("--sports", type=str, default="NBA")
    parser.add_argument("--config", type=str)
    parser.add_argument("--record", action="store_true",
                        help="Record live snapshots instead of backtesting")
    parser.add_argument("--duration", type=int, default=3600,
                        help="Recording duration (seconds)")
    parser.add_argument("--interval", type=int, default=30,
                        help="Recording interval (seconds)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(yaml_path=args.config)

    if args.record:
        asyncio.run(record_snapshots(cfg, args.duration, args.interval, args.snapshots))
        return

    snapshots = load_snapshots(args.snapshots)
    if not snapshots:
        print("No snapshots found")
        return

    sports = [Sport(s.strip().upper()) for s in args.sports.split(",")]
    result = run_backtest(snapshots, cfg, args.bankroll, sports_filter=sports)

    print("\n" + "="*60)
    print("BACKTEST RESULTS")
    print("="*60)
    print(f"Snapshots analyzed:    {result.n_snapshots}")
    print(f"Opportunities found:   {result.n_opportunities}")
    print(f"Opportunities filled:  {result.n_executed}")
    print(f"Win rate:              {result.win_rate*100:.1f}%")
    print(f"Realized PnL:          ${result.realized_pnl_usdc:,.2f}")
    print(f"Total capital deployed: ${result.total_cost_usdc:,.2f}")
    print(f"ROI:                   {result.roi_pct:.2f}%")
    print(f"Avg edge (detected):   {result.avg_edge_bps:.1f} bps")
    print(f"Avg slippage:          {result.avg_slippage_bps:.1f} bps")
    print(f"Max drawdown:          ${result.max_drawdown_usdc:,.2f}")
    print()
    print("By strategy type:")
    for t, stats in result.by_type.items():
        roi = (stats["pnl"] / stats["cost"] * 100) if stats["cost"] > 0 else 0
        print(f"  {t:20s} n={stats['n']:4d}  "
              f"PnL=${stats['pnl']:>10.2f}  cost=${stats['cost']:>10.2f}  ROI={roi:5.2f}%")


if __name__ == "__main__":
    main()
