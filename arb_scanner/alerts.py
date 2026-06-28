"""
alerts.py — Telegram & Discord notifications.

Sends alerts on:
    - Opportunity detected (≥ min_edge_alert_bps)
    - Order filled (with realized P&L)
    - Execution error
    - Market dispute / resolution issue
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from config import Config
from models import Opportunity, Position

log = logging.getLogger(__name__)


class AlertSender:
    """Sends alerts to Telegram, Discord, or both."""

    def __init__(self, cfg: Config):
        self.cfg = cfg.alerts
        self.client = httpx.AsyncClient(timeout=10.0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def send_opportunity_alert(self, opp: Opportunity):
        """Send alert when an opportunity is detected."""
        if opp.net_edge_bps < self.cfg.min_edge_alert_bps:
            return

        msg = (
            f"[ARB] *Arb Opportunity*\n"
            f"Type: `{opp.type.value}`\n"
            f"Event: `{opp.event_slug}`\n"
            f"Net edge: *{opp.net_edge_bps:.0f} bps* ({opp.net_edge_bps/100:.2f}%)\n"
            f"Cost: ${opp.total_cost:.2f}\n"
            f"Guaranteed payout: ${opp.guaranteed_payout:.2f}\n"
            f"Net profit: ${opp.net_edge:.2f}\n"
            f"Legs: {len(opp.legs)}\n"
            f"Detected: {datetime.fromtimestamp(opp.detected_at, tz=timezone.utc).isoformat()}"
        )
        await self._send_all(msg)

    async def send_fill_alert(self, position: Position):
        """Send alert when an order fills."""
        if not self.cfg.alert_on_fill:
            return
        msg = (
            f"[OK] *Position Filled*\n"
            f"Opp ID: `{position.opportunity_id}`\n"
            f"Status: `{position.status.value}`\n"
            f"Total cost: ${position.total_cost:.2f}\n"
            f"Legs filled: {sum(1 for s in position.filled_shares if s > 0)}/{len(position.legs)}\n"
        )
        for i, (leg, filled, avg) in enumerate(zip(position.legs, position.filled_shares, position.avg_fill_prices)):
            msg += f"  Leg {i+1}: {leg.side.value} {filled:.0f} @ ${avg:.4f}\n"
        await self._send_all(msg)

    async def send_error_alert(self, error: str, context: str = ""):
        """Send alert on execution error."""
        if not self.cfg.alert_on_error:
            return
        msg = (
            f"[ERR] *Error*\n"
            f"Context: `{context}`\n"
            f"Error: `{error[:500]}`\n"
            f"Time: {datetime.now(timezone.utc).isoformat()}"
        )
        await self._send_all(msg)

    async def send_dispute_alert(self, market_id: str, reason: str):
        """Send alert when a market enters UMA dispute."""
        if not self.cfg.alert_on_dispute:
            return
        msg = (
            f"[!] *Market Dispute*\n"
            f"Market: `{market_id}`\n"
            f"Reason: {reason}\n"
            f"Action: Manual review required"
        )
        await self._send_all(msg)

    async def send_daily_summary(self, stats: dict):
        """Send daily PnL summary."""
        msg = (
            f"[STATS] *Daily Summary*\n"
            f"Realized PnL: ${stats.get('realized_pnl', 0):.2f}\n"
            f"Closed positions: {stats.get('n_closed', 0)}\n"
            f"Win rate: {stats.get('win_rate', 0)*100:.1f}%\n"
            f"Avg edge: {stats.get('avg_edge_bps', 0):.0f} bps\n"
            f"Open exposure: ${stats.get('open_exposure', 0):.2f}"
        )
        await self._send_all(msg)

    # ───────────────────────────────────────────────────────────────────────
    # Transport: Telegram
    # ───────────────────────────────────────────────────────────────────────

    async def _send_telegram(self, text: str):
        if not self.cfg.telegram_bot_token or not self.cfg.telegram_chat_id:
            return
        url = f"https://api.telegram.org/bot{self.cfg.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": self.cfg.telegram_chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        try:
            r = await self.client.post(url, json=payload)
            if r.status_code != 200:
                log.warning(f"Telegram alert failed: {r.status_code} {r.text[:200]}")
        except Exception as e:
            log.warning(f"Telegram alert error: {e}")

    # ───────────────────────────────────────────────────────────────────────
    # Transport: Discord webhook
    # ───────────────────────────────────────────────────────────────────────

    async def _send_discord(self, text: str):
        if not self.cfg.discord_webhook_url:
            return
        # Discord has a 2000-char limit per message
        for i in range(0, len(text), 1900):
            chunk = text[i:i+1900]
            payload = {"content": chunk}
            try:
                r = await self.client.post(self.cfg.discord_webhook_url, json=payload)
                if r.status_code not in (200, 204):
                    log.warning(f"Discord alert failed: {r.status_code}")
            except Exception as e:
                log.warning(f"Discord alert error: {e}")
            if i + 1900 < len(text):
                await asyncio.sleep(0.5)  # rate limit safety

    async def _send_all(self, text: str):
        """Send to all configured channels in parallel."""
        tasks = [self._send_telegram(text), self._send_discord(text)]
        await asyncio.gather(*tasks, return_exceptions=True)
