"""
optimizer.py — Linear programming for combinatorial arbitrage.

Solves the covering portfolio problem:
    Given a set of binary markets on the same event and the set of all
    feasible atomic outcomes, find the minimum-cost basket of (market, side)
    positions that pays at least $1 in every atomic outcome.

Formulation:
    Variables:
        x[(market, YES)] ≥ 0   (shares of YES to buy on this market)
        x[(market, NO)]  ≥ 0   (shares of NO to buy on this market)

    Objective:
        minimize  Σ_i  cost_i * x_i
        where cost_i = best_ask price for the corresponding side

    Constraints:
        For each atomic outcome j:
            Σ_i  payoff(i, j) * x_i  ≥  1
        where payoff(i, j) = 1 if position i wins in outcome j, else 0.

    If optimal_cost < 1 - fee_buffer, an arb exists.
    Profit per $1 of guaranteed payout = 1 - optimal_cost - fees.

Implementation uses PuLP (https://coin-or.github.io/pulp/).
    pip install pulp
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from models import (
    AtomicOutcome, Config, Market, MarketCategory, Side,
)
from config import taker_fee_rate

log = logging.getLogger(__name__)

try:
    import pulp
    HAS_PULP = True
except ImportError:
    HAS_PULP = False
    log.warning("PuLP not installed; combinatorial detector will be skipped. Install with: pip install pulp")


# ─────────────────────────────────────────────────────────────────────────────
# Feasibility rules — prune physically impossible atomic outcomes
# ─────────────────────────────────────────────────────────────────────────────

def is_feasible_outcome(
    outcome: AtomicOutcome,
    markets: List[Market],
) -> bool:
    """Check whether an atomic outcome is physically possible.

    For NBA/NFL-style events with moneyline + spread on the same game:
        - If home team wins outright, did they cover the spread?
          - If spread_value < 0 (home favored) and margin > |spread|: cover
          - If spread_value < 0 and margin < |spread|: no cover
          - If home loses outright: no cover (always)
        This means the combination "home wins AND home does NOT cover -3.5"
        IS feasible (win by 1-3 points), but "home wins AND home does NOT
        cover +3.5" is INFEASIBLE (if home wins, they necessarily cover +3.5).

    We encode these constraints heuristically. For production use, expand
    this function with sport-specific logic.
    """
    # Group outcomes by market category
    by_cat: Dict[str, str] = {}
    spreads = [m for m in markets if m.category == MarketCategory.SPREAD]
    moneylines = [m for m in markets if m.category == MarketCategory.MONEYLINE]
    totals = [m for m in markets if m.category == MarketCategory.TOTAL]

    # Find moneyline result
    ml_winner = None  # "home" or "away"
    for m in moneylines:
        if m.condition_id in outcome.outcomes:
            res = outcome.outcomes[m.condition_id]
            # Convention: market question "Will home win?" → YES = home wins
            # This is a simplification — real parsing needs NLP
            ml_winner = "home" if res == "YES" else "away"

    # Check spread consistency
    for m in spreads:
        if m.condition_id not in outcome.outcomes:
            continue
        spread_res = outcome.outcomes[m.condition_id]
        # If home is favored (spread < 0) and home wins outright:
        #   - home covers iff margin > |spread|
        #   - This outcome is feasible either way (margin can be anything ≥ 0)
        # If home is favored (spread < 0) and home loses:
        #   - home does NOT cover (always)
        #   - So "away wins AND home COVERS -3.5" is INFEASIBLE
        # If home is underdog (spread > 0) and home wins:
        #   - home covers (always)
        #   - So "home wins AND home does NOT cover +3.5" is INFEASIBLE
        if m.spread_value is not None:
            home_favored = m.spread_value < 0
            home_covers = spread_res == "YES"

            if home_favored and ml_winner == "away" and home_covers:
                return False  # away wins but home covers as favorite — impossible
            if not home_favored and ml_winner == "home" and not home_covers:
                return False  # home wins outright but doesn't cover as underdog — impossible

    return True


# ─────────────────────────────────────────────────────────────────────────────
# Payoff matrix construction
# ─────────────────────────────────────────────────────────────────────────────

def _position_pays(position: Tuple[Market, Side], outcome: AtomicOutcome) -> bool:
    """Does buying (market, side) pay $1 in this atomic outcome?"""
    market, side = position
    res = outcome.outcomes.get(market.condition_id)
    if res is None:
        return False
    return (side == Side.YES and res == "YES") or (side == Side.NO and res == "NO")


def _position_cost(position: Tuple[Market, Side]) -> float:
    """Cost to buy one share of this position (best ask)."""
    market, side = position
    if not market.book:
        return float("inf")
    if side == Side.YES:
        return market.book.best_ask.price if market.book.best_ask else float("inf")
    else:
        # NO cost = 1 - YES bid
        return (1.0 - market.book.best_bid.price) if market.book.best_bid else float("inf")


# ─────────────────────────────────────────────────────────────────────────────
# LP solver
# ─────────────────────────────────────────────────────────────────────────────

def solve_covering_lp(
    markets: List[Market],
    atomic_outcomes: List[AtomicOutcome],
    cfg: Config,
) -> Optional[Tuple[float, Dict[Tuple[Market, Side], float]]]:
    """Solve the min-cost covering portfolio LP.

    Returns:
        (optimal_cost, allocation) where allocation maps (market, side) → shares
        Returns None if LP is infeasible or PuLP not installed.
    """
    if not HAS_PULP:
        return None

    # Filter to feasible outcomes only
    feasible = [o for o in atomic_outcomes if is_feasible_outcome(o, markets)]
    if not feasible:
        log.debug("No feasible atomic outcomes after constraint pruning")
        return None

    # Build candidate positions: (YES, NO) for each market
    positions: List[Tuple[Market, Side]] = []
    for m in markets:
        if not m.book:
            continue
        if m.book.best_ask:
            positions.append((m, Side.YES))
        if m.book.best_bid:
            positions.append((m, Side.NO))

    if not positions:
        return None

    # Setup LP
    prob = pulp.LpProblem("covering_portfolio", pulp.LpMinimize)

    # Variables: x[(market_id, side)] ≥ 0
    x = {
        (m.condition_id, s): pulp.LpVariable(f"x_{m.condition_id[:8]}_{s.value}", lowBound=0)
        for (m, s) in positions
    }

    # Objective: minimize Σ cost_i * x_i
    prob += pulp.lpSum(
        _position_cost((m, s)) * x[(m.condition_id, s)]
        for (m, s) in positions
    )

    # Constraints: for each atomic outcome, Σ payoff * x ≥ 1
    for j, outcome in enumerate(feasible):
        prob += pulp.lpSum(
            (1.0 if _position_pays((m, s), outcome) else 0.0) * x[(m.condition_id, s)]
            for (m, s) in positions
        ) >= 1.0, f"cover_outcome_{j}"

    # Solve silently
    try:
        prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=5))
    except Exception as e:
        log.warning(f"LP solver failed: {e}")
        return None

    if prob.status != pulp.constants.LpStatusOptimal:
        log.debug(f"LP not optimal: status={pulp.LpStatus[prob.status]}")
        return None

    # Extract solution
    allocation: Dict[Tuple[Market, Side], float] = {}
    for (m, s) in positions:
        val = x[(m.condition_id, s)].value() or 0.0
        if val > 1e-6:
            allocation[(m, s)] = val

    optimal_cost = pulp.value(prob.objective) or 0.0
    return optimal_cost, allocation


# ─────────────────────────────────────────────────────────────────────────────
# Greedy fallback (if PuLP not available or for quick scan)
# ─────────────────────────────────────────────────────────────────────────────

def greedy_cover_heuristic(
    markets: List[Market],
    atomic_outcomes: List[AtomicOutcome],
    cfg: Config,
) -> Optional[Tuple[float, Dict[Tuple[Market, Side], float]]]:
    """Greedy covering set: at each step, pick the cheapest position that
    covers the most uncovered outcomes.

    This is a set-cover approximation — O(log N) ratio from optimal.
    Useful as a fast pre-filter or fallback when PuLP isn't available.
    """
    feasible = [o for o in atomic_outcomes if is_feasible_outcome(o, markets)]
    if not feasible:
        return None

    positions: List[Tuple[Market, Side]] = []
    for m in markets:
        if m.book and m.book.best_ask:
            positions.append((m, Side.YES))
        if m.book and m.book.best_bid:
            positions.append((m, Side.NO))

    uncovered = set(range(len(feasible)))
    allocation: Dict[Tuple[Market, Side], float] = {}
    total_cost = 0.0

    while uncovered:
        # Score each position: (outcomes_covered / cost)
        best_score = -1
        best_pos = None
        best_covered = set()
        for pos in positions:
            cost = _position_cost(pos)
            if cost <= 0 or cost == float("inf"):
                continue
            covered = {
                j for j in uncovered
                if _position_pays(pos, feasible[j])
            }
            if not covered:
                continue
            score = len(covered) / cost
            if score > best_score:
                best_score = score
                best_pos = pos
                best_covered = covered

        if best_pos is None:
            log.debug("Greedy cover: cannot cover remaining outcomes")
            return None

        # Buy enough shares to cover (1 share per outcome)
        # In simple case: 1 share suffices since each outcome needs ≥1 payout
        allocation[best_pos] = allocation.get(best_pos, 0) + 1.0
        total_cost += _position_cost(best_pos)
        uncovered -= best_covered

    return total_cost, allocation


if __name__ == "__main__":
    # Quick test with synthetic data
    print("Testing LP solver...")
    print(f"PuLP available: {HAS_PULP}")
    print("Run with real market data via scanner.py")
