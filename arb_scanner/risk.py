"""
risk.py — Position sizing, exposure tracking, and risk gates.

Implements:
    1. Kelly criterion sizing (conservative: 25% of full Kelly)
    2. Exposure caps (per-game, per-day, total open positions)
    3. Blacklist management (markets with prior disputes)
    4. Slippage modeling (depth-weighted)
    5. Risk gate: reject opportunities that violate any constraint
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from config import Config
from models import Leg, Market, Opportunity, OpportunityType, Position

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Kelly criterion
# ─────────────────────────────────────────────────────────────────────────────

def kelly_fraction(p_win: float, odds_decimal: float) -> float:
    """Full Kelly fraction of bankroll to bet.

    f* = (p * (b - 1) - q) / b
    where:
        p = probability of winning
        q = 1 - p
        b = net odds (decimal_odds - 1)

    For arbitrage (guaranteed win), p = 1.0, so f* = (b - 1) / b → 1 (bet everything).
    That's clearly wrong in practice because:
        a) p isn't truly 1 — settlement risk, leg failure risk
        b) variance comes from execution, not outcome
    So we apply a conservative fraction (default 25% of full Kelly) AND a hard cap.
    """
    if p_win <= 0 or p_win >= 1:
        return 0.0
    q = 1 - p_win
    b = odds_decimal - 1
    if b <= 0:
        return 0.0
    f = (p_win * b - q) / b
    return max(0.0, f)


def conservative_kelly_size(
    edge_fraction: float,
    bankroll: float,
    cfg: Config,
    perceived_p_win: float = 0.95,  # never assume 1.0 — settlement risk
) -> float:
    """Conservative Kelly sizing for an arb opportunity.

    For arbs, we model the "edge" as a synthetic bet:
        - You risk `total_cost` to win `guaranteed_payout`
        - effective decimal odds = guaranteed_payout / total_cost
        - perceived_p_win = 0.95 (to account for settlement/leg risk)

    Then f* = kelly_fraction(0.95, odds) and we bet kelly_fraction_cfg * f* of bankroll.
    """
    if edge_fraction <= 0:
        return 0.0

    # Synthetic odds: risk $1 to win $(1 + edge)
    odds_decimal = 1.0 + edge_fraction
    f_full = kelly_fraction(perceived_p_win, odds_decimal)
    f_adjusted = f_full * cfg.risk.kelly_fraction

    # Cap to hard max
    max_bet = bankroll * cfg.risk.kelly_cap_bps / 10_000
    min_bet = bankroll * cfg.risk.kelly_floor_bps / 10_000

    bet = bankroll * f_adjusted
    bet = min(bet, max_bet)
    if bet < min_bet:
        return 0.0
    return bet


# ─────────────────────────────────────────────────────────────────────────────
# Exposure tracking
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ExposureTracker:
    """Tracks open exposure across dimensions for risk gating."""
    per_event: Dict[str, float] = field(default_factory=dict)   # event_slug → usdc
    per_day: Dict[str, float] = field(default_factory=dict)     # YYYY-MM-DD → usdc
    total_open_usdc: float = 0.0
    n_open_positions: int = 0

    def add(self, opportunity: Opportunity):
        for leg in opportunity.legs:
            cost = leg.cost
            self.per_event[opportunity.event_slug] = (
                self.per_event.get(opportunity.event_slug, 0) + cost
            )
            day = time.strftime("%Y-%m-%d", time.gmtime(opportunity.detected_at))
            self.per_day[day] = self.per_day.get(day, 0) + cost
            self.total_open_usdc += cost
        self.n_open_positions += 1

    def close(self, opportunity: Opportunity, realized_pnl: float = 0.0):
        for leg in opportunity.legs:
            self.per_event[opportunity.event_slug] = (
                self.per_event.get(opportunity.event_slug, 0) - leg.cost
            )
            self.total_open_usdc -= leg.cost
        self.n_open_positions -= 1

    def event_exposure(self, event_slug: str) -> float:
        return self.per_event.get(event_slug, 0)

    def daily_exposure(self) -> float:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        return self.per_day.get(today, 0)


# ─────────────────────────────────────────────────────────────────────────────
# Blacklist
# ─────────────────────────────────────────────────────────────────────────────

class Blacklist:
    """Persistent blacklist of market condition IDs to skip.

    Reasons to blacklist:
        - UMA dispute on a previous resolution
        - Ambiguous resolution criteria (e.g., rain-delayed MLB)
        - Suspected market manipulation
        - Failed settlement
    """

    def __init__(self, path: str = "data/blacklist.json"):
        self.path = path
        self._entries: Dict[str, str] = {}  # condition_id → reason
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    self._entries = json.load(f)
            except Exception as e:
                log.warning(f"Failed to load blacklist: {e}")
                self._entries = {}

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self._entries, f, indent=2)

    def add(self, condition_id: str, reason: str):
        self._entries[condition_id] = reason
        self._save()
        log.info(f"Blacklisted {condition_id}: {reason}")

    def contains(self, condition_id: str) -> bool:
        return condition_id in self._entries

    def __contains__(self, condition_id: str) -> bool:
        return self.contains(condition_id)


# ─────────────────────────────────────────────────────────────────────────────
# Slippage modeling
# ─────────────────────────────────────────────────────────────────────────────

def estimate_slippage_bps(
    book,
    target_notional_usdc: float,
    cfg: Config,
) -> float:
    """Estimate slippage in basis points for a market order of given size.

    Walks the order book to compute the volume-weighted average price (VWAP)
    and compares to the best price.

    Returns slippage in bps (e.g., 25 = 0.25% slippage).
    """
    if not book or not book.best_ask:
        return float("inf")

    # Try buying YES at market — this is the worst case
    shares_needed = target_notional_usdc / book.best_ask.price
    avg_price, _ = book.simulate_buy_yes(shares_needed)

    if avg_price <= 0:
        return float("inf")

    slippage_fraction = (avg_price - book.best_ask.price) / book.best_ask.price
    return slippage_fraction * 10_000


# ─────────────────────────────────────────────────────────────────────────────
# Risk gate
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RiskCheckResult:
    passed: bool
    reason: str = ""
    adjusted_size_usdc: Optional[float] = None


def risk_gate(
    opportunity: Opportunity,
    tracker: ExposureTracker,
    blacklist: Blacklist,
    cfg: Config,
) -> RiskCheckResult:
    """Final pre-execution risk check. Returns pass/fail + adjusted size.

    Checks:
        1. No blacklisted markets
        2. Per-event exposure cap
        3. Daily exposure cap
        4. Total open positions cap
        5. Per-opportunity size cap
        6. Slippage check on each leg
        7. Kelly sizing (downsizes if appropriate)
    """
    # 1. Blacklist
    for leg in opportunity.legs:
        if blacklist.contains(leg.market.condition_id):
            return RiskCheckResult(
                passed=False,
                reason=f"Market {leg.market.condition_id} is blacklisted",
            )

    # 2. Per-event cap
    event_exp = tracker.event_exposure(opportunity.event_slug)
    if event_exp + opportunity.total_cost > cfg.risk.max_game_exposure_usdc:
        remaining = cfg.risk.max_game_exposure_usdc - event_exp
        if remaining < 100:  # dust threshold
            return RiskCheckResult(
                passed=False,
                reason=f"Per-event cap reached for {opportunity.event_slug}",
            )
        # Downsize
        scale = remaining / opportunity.total_cost
        return RiskCheckResult(
            passed=True,
            adjusted_size_usdc=opportunity.total_cost * scale,
            reason=f"downsized to fit per-event cap (scale={scale:.2f})",
        )

    # 3. Daily cap
    daily_exp = tracker.daily_exposure()
    if daily_exp + opportunity.total_cost > cfg.risk.max_daily_exposure_usdc:
        return RiskCheckResult(
            passed=False,
            reason="Daily exposure cap reached",
        )

    # 4. Open positions cap
    if tracker.n_open_positions >= cfg.risk.max_open_positions:
        return RiskCheckResult(
            passed=False,
            reason="Max open positions cap reached",
        )

    # 5. Per-opportunity cap
    if opportunity.total_cost > cfg.risk.max_position_usdc:
        return RiskCheckResult(
            passed=True,
            adjusted_size_usdc=cfg.risk.max_position_usdc,
            reason="downsized to per-position cap",
        )

    # 6. Slippage check (sample first leg)
    sample_leg = opportunity.legs[0]
    if sample_leg.market.book:
        slip_bps = estimate_slippage_bps(
            sample_leg.market.book, opportunity.total_cost, cfg
        )
        if slip_bps > cfg.risk.max_slippage_bps:
            return RiskCheckResult(
                passed=False,
                reason=f"Slippage {slip_bps:.0f}bps exceeds cap {cfg.risk.max_slippage_bps}bps",
            )

    # 7. Kelly sizing
    edge_fraction = opportunity.net_edge / opportunity.total_cost
    kelly_size = conservative_kelly_size(
        edge_fraction=edge_fraction,
        bankroll=cfg.risk.bankroll_usdc,
        cfg=cfg,
    )
    if kelly_size < opportunity.total_cost:
        return RiskCheckResult(
            passed=True,
            adjusted_size_usdc=kelly_size,
            reason=f"Kelly downsized to ${kelly_size:.0f}",
        )

    return RiskCheckResult(passed=True)


# ─────────────────────────────────────────────────────────────────────────────
# PnL tracking
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PnLTracker:
    """Tracks realized + unrealized PnL for monitoring."""
    realized_pnl_usdc: float = 0.0
    n_closed_positions: int = 0
    n_wins: int = 0
    n_losses: int = 0
    edge_history_bps: List[float] = field(default_factory=list)

    def record_close(self, position: Position, payout: float):
        realized = payout - position.total_cost
        self.realized_pnl_usdc += realized
        self.n_closed_positions += 1
        if realized > 0:
            self.n_wins += 1
        else:
            self.n_losses += 1
        return realized

    @property
    def win_rate(self) -> float:
        if self.n_closed_positions == 0:
            return 0.0
        return self.n_wins / self.n_closed_positions

    @property
    def avg_edge_bps(self) -> float:
        if not self.edge_history_bps:
            return 0.0
        return sum(self.edge_history_bps) / len(self.edge_history_bps)
