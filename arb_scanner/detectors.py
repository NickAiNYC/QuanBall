"""
detectors.py — Arbitrage opportunity detection.

Each detector is a pure function: (markets, config) -> List[Opportunity].
No I/O. No side effects. Easy to unit test.

Detectors implemented:
    1. detect_single_market_arb      — YES + NO sum < $1 (the bread & butter)
    2. detect_negrisk_rebalance_arb  — multi-outcome NegRisk sum drift
    3. detect_combinatorial_arb      — cross-market covering portfolio (LP)
    4. detect_cross_platform_arb     — Polymarket vs external sportsbook lines

Edge calculations include fee impact:
    - Maker orders (limit): fee = 0
    - Taker orders (market): fee = 0.75% per leg
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Dict, List, Optional, Tuple

from config import (
    Config, TAKER_FEE_BPS, MAKER_FEE_BPS,
    taker_fee_rate, maker_fee_rate,
)
from models import (
    AtomicOutcome, Event, Leg, Market, MarketCategory, Opportunity,
    OpportunityType, OrderBook, Side, Sport,
)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _opp_id(*parts) -> str:
    """Stable ID from the parts that define an opportunity."""
    h = hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()[:12]
    return h


def _bps(fraction: float) -> float:
    return fraction * 10_000


def _fee_rate(is_maker: bool) -> float:
    return maker_fee_rate() if is_maker else taker_fee_rate()


def _net_cost_with_fee(price: float, shares: float, is_maker: bool) -> float:
    """Total cost of buying `shares` at `price`, including fee."""
    gross = price * shares
    fee = gross * _fee_rate(is_maker)
    return gross + fee


def _net_proceeds_with_fee(price: float, shares: float, is_maker: bool) -> float:
    """Net proceeds from selling `shares` at `price`, after fee."""
    gross = price * shares
    fee = gross * _fee_rate(is_maker)
    return gross - fee


def _liquidity_check(book: OrderBook, min_depth_usdc: float, levels: int = 5) -> bool:
    """Verify both sides of the book have enough depth."""
    bid_depth, ask_depth = book.depth_usd(levels=levels)
    return bid_depth >= min_depth_usdc and ask_depth >= min_depth_usdc


# ─────────────────────────────────────────────────────────────────────────────
# 1. Single-market arbitrage (YES + NO sum < $1)
# ─────────────────────────────────────────────────────────────────────────────

def detect_single_market_arb(
    market: Market,
    cfg: Config,
) -> Optional[Opportunity]:
    """Detect YES+NO arbitrage in a single binary market.

    Strategy: Buy YES at ask + Buy NO at (1 - YES bid). If total < $1, arb exists.
        Cost = YES_ask + NO_ask = YES_ask + (1 - YES_bid)
        If YES_ask + (1 - YES_bid) < 1 - fee_buffer, we have an edge.

    The "natural" way (buy YES at ask, buy NO at ask) is what most tutorials
    describe, but Polymarket NO is minted from YES, so NO ask = 1 - YES bid.
    Therefore the cheapest way to acquire both sides is:
        Buy YES at the ask (cross the spread on YES side)
        Buy NO at the bid-equivalent (sell YES-equivalent at bid)
    Net cost = YES_ask + (1 - YES_bid) = 1 + spread

    So actually, single-market YES+NO arb in a healthy market always costs
    MORE than $1 (you pay the spread). The arb appears when:
        - An external shock hits and the book hasn't re-priced yet
        - A taker crosses both sides in rapid succession leaving stale orders
        - A market maker pulls quotes and leaves the book imbalanced

    Detection: compute the cost of acquiring both YES and NO at the BEST
    AVAILABLE prices (yes_ask for YES, equivalent for NO), and check if
    total < $1 - fee_buffer.

    Two execution modes:
        TAKER: cross both sides immediately. fee = 0.75% per leg.
        MAKER: rest both sides as limit orders. fee = 0, but fill risk.
    """
    if market.book is None or market.market_type != MarketType.BINARY:
        return None

    book = market.book
    if not book.best_ask or not book.best_bid:
        return None

    # Liquidity filter
    if not _liquidity_check(book, cfg.scanner.min_liquidity_usdc):
        return None

    # ─── TAKER path ───
    yes_ask = book.best_ask.price  # cost to buy 1 YES
    no_cost = 1.0 - book.best_bid.price  # cost to buy 1 NO (= sell YES at bid)
    total_cost_taker = yes_ask + no_cost
    payout_per_share = 1.0  # exactly $1 either way

    fee_taker = total_cost_taker * taker_fee_rate()  # fee on both legs
    net_cost_taker = total_cost_taker + fee_taker
    net_edge_taker = payout_per_share - net_cost_taker
    edge_bps_taker = _bps(net_edge_taker / total_cost_taker) if total_cost_taker > 0 else 0

    # ─── MAKER path (preferred when possible) ───
    # As maker, we'd rest YES bid at (1 - yes_ask) and NO bid at (1 - no_cost)
    # Realistically for arb we'd want to rest at mid - epsilon to get filled
    # Simplified: assume we can maker-fill at mid price for both legs
    if book.mid is not None:
        mid = book.mid
        # Maker rest at mid: buy YES at mid, sell YES at mid (= buy NO at 1-mid)
        # But you can't simultaneously maker-fill both sides — that's just holding
        # The maker arb shows up when spread is wide: rest YES bid below mid,
        # rest YES ask (= NO bid) above mid. If both fill, you pocket the spread.
        spread = book.spread or 0
        # Maker profit = spread - 0 fee (per share, both legs filled)
        maker_profit_per_share = spread
        # Cost basis = mid * 2 (you bought YES at mid - s/2 and sold at mid + s/2)
        # Actually for arb: rest limit BUY YES at (mid - s/2) and limit BUY NO at (1 - mid - s/2)
        # If both fill, total cost = (mid - s/2) + (1 - mid - s/2) = 1 - s
        # Payout = $1. Profit = s (the spread). Maker fee = 0.
        maker_total_cost = 1.0 - spread
        maker_edge = spread
        edge_bps_maker = _bps(maker_edge / maker_total_cost) if maker_total_cost > 0 else 0
    else:
        maker_edge = 0
        edge_bps_maker = 0

    # ─── Pick the better execution path ───
    best_edge_bps = max(edge_bps_taker, edge_bps_maker)
    is_maker = edge_bps_maker > edge_bps_taker

    # Threshold check (maker threshold is lower because no fee)
    threshold = (
        cfg.scanner.min_edge_maker_bps if is_maker
        else cfg.scanner.min_edge_taker_bps
    )

    if best_edge_bps < threshold:
        return None

    # Build opportunity with conservative (taker) sizing
    # Use min of bid/ask depth as max shares we can fill
    bid_depth, ask_depth = book.depth_usd(levels=5)
    max_shares_by_depth = min(
        ask_depth / yes_ask if yes_ask > 0 else 0,
        bid_depth / no_cost if no_cost > 0 else 0,
    )

    # Cap by configured max position
    cost_per_share = total_cost_taker if not is_maker else maker_total_cost
    max_shares_by_position = cfg.risk.max_position_usdc / cost_per_share
    shares = min(max_shares_by_depth, max_shares_by_position)

    if shares < 10:  # dust filter
        return None

    # Build legs
    legs = [
        Leg(
            market=market,
            side=Side.YES,
            price=yes_ask if not is_maker else (book.mid - (book.spread or 0)/2),
            shares=shares,
            cost=yes_ask * shares if not is_maker else (book.mid - (book.spread or 0)/2) * shares,
            is_maker=is_maker,
        ),
        Leg(
            market=market,
            side=Side.NO,
            price=no_cost if not is_maker else (1 - book.mid - (book.spread or 0)/2),
            shares=shares,
            cost=no_cost * shares if not is_maker else (1 - book.mid - (book.spread or 0)/2) * shares,
            is_maker=is_maker,
        ),
    ]

    total_cost = sum(l.cost for l in legs)
    if is_maker:
        # Maker fee = 0
        net_cost = total_cost
    else:
        net_cost = total_cost * (1 + taker_fee_rate())

    guaranteed_payout = shares  # exactly $1 per share regardless of outcome
    gross_edge = guaranteed_payout - total_cost
    net_edge = guaranteed_payout - net_cost
    net_edge_bps = _bps(net_edge / total_cost) if total_cost > 0 else 0

    return Opportunity(
        id=_opp_id(market.condition_id, int(time.time() * 1000)),
        type=OpportunityType.SINGLE_MARKET,
        event_slug=market.event_slug,
        legs=legs,
        total_cost=total_cost,
        guaranteed_payout=guaranteed_payout,
        gross_edge=gross_edge,
        net_edge=net_edge,
        net_edge_bps=net_edge_bps,
        detected_at=time.time(),
        expires_at=time.time() + 30,  # stale after 30s
        metadata={
            "yes_ask": yes_ask,
            "no_cost": no_cost,
            "spread": book.spread,
            "is_maker_path": is_maker,
            "max_shares": shares,
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. NegRisk multi-outcome rebalance arb
# ─────────────────────────────────────────────────────────────────────────────

def detect_negrisk_rebalance_arb(
    event: Event,
    cfg: Config,
) -> Optional[Opportunity]:
    """Detect arbitrage in a multi-outcome NegRisk market.

    NegRisk markets: one event with N outcomes (e.g., "Who wins the NBA MVP?").
    Each outcome has a YES token. The sum of YES prices should ≈ $1
    (minus overround). When sum drifts below $1 - fee_buffer, buy all YESes.
    When sum drifts above $1 + fee_buffer, sell all YESes (or buy NOs).

    NegRisk settlement: exactly one outcome resolves YES. Holding 1 share
    of every YES guarantees $1 payout.

    Note: Per the article, sports has very few NegRisk rebalance opps
    compared to politics. This detector is included for completeness.
    """
    # Filter to NegRisk markets on this event
    neg_markets = [m for m in event.markets if m.neg_risk and m.book]
    if len(neg_markets) < 3:  # need at least 3 outcomes
        return None

    # Compute sum of YES asks (cost to buy one share of each YES)
    sum_yes_asks = 0.0
    sum_yes_bids = 0.0
    valid_markets = []
    for m in neg_markets:
        if not m.book or not m.book.best_ask or not m.book.best_bid:
            continue
        if not _liquidity_check(m.book, cfg.scanner.min_liquidity_usdc / 2):
            continue  # NegRisk markets are typically thinner
        sum_yes_asks += m.book.best_ask.price
        sum_yes_bids += m.book.best_bid.price
        valid_markets.append(m)

    if len(valid_markets) < 3:
        return None

    # Buy-all-YESes arb: if sum(asks) < $1, buy all YESes
    fee_taker = sum_yes_asks * taker_fee_rate()
    net_cost_buy_all = sum_yes_asks + fee_taker
    edge_buy_all = 1.0 - net_cost_buy_all
    edge_bps_buy = _bps(edge_buy_all / sum_yes_asks) if sum_yes_asks > 0 else 0

    # Sell-all-YESes arb: if sum(bids) > $1, sell all YESes (short via NOs)
    # Equivalent: buy all NOs at (1 - YES_bid) for each, total = N - sum(bids)
    # If sum(bids) > $1 + fee, this is profitable — but requires borrowing YESes
    # Polymarket doesn't have native shorts, so this path needs the NO side:
    # Buy 1 NO on each market. Cost = sum(1 - yes_bid) = N - sum(yes_bid).
    # Payout: $1 on the losing markets (all but one), $0 on winner. Total = N - 1.
    # Profit = (N - 1) - (N - sum(bids)) = sum(bids) - 1. So same as selling YESes.
    n = len(valid_markets)
    no_total_cost = n - sum_yes_bids
    no_fee = no_total_cost * taker_fee_rate()
    no_payout = n - 1  # N-1 NOs pay out (all but the winner)
    edge_sell_all = no_payout - (no_total_cost + no_fee)
    edge_bps_sell = _bps(edge_sell_all / no_total_cost) if no_total_cost > 0 else 0

    best_edge_bps = max(edge_bps_buy, edge_bps_sell)
    if best_edge_bps < cfg.scanner.min_edge_negrisk_bps:
        return None

    if edge_bps_buy >= edge_bps_sell:
        # Buy all YESes
        shares_per_market = min(
            cfg.risk.max_position_usdc / sum_yes_asks,
            min(m.book.best_ask.size for m in valid_markets),
        )
        legs = [
            Leg(
                market=m,
                side=Side.YES,
                price=m.book.best_ask.price,
                shares=shares_per_market,
                cost=m.book.best_ask.price * shares_per_market,
                is_maker=False,
            )
            for m in valid_markets
        ]
        total_cost = sum_yes_asks * shares_per_market
        guaranteed_payout = shares_per_market  # exactly one YES wins
    else:
        # Buy all NOs
        shares_per_market = min(
            cfg.risk.max_position_usdc / no_total_cost,
            min(m.book.best_bid.size for m in valid_markets)
        )
        legs = [
            Leg(
                market=m,
                side=Side.NO,
                price=1.0 - m.book.best_bid.price,
                shares=shares_per_market,
                cost=(1.0 - m.book.best_bid.price) * shares_per_market,
                is_maker=False,
            )
            for m in valid_markets
        ]
        total_cost = no_total_cost * shares_per_market
        guaranteed_payout = (n - 1) * shares_per_market  # all NOs except winner's

    if shares_per_market < 5:  # dust filter
        return None

    gross_edge = guaranteed_payout - total_cost
    net_cost = total_cost * (1 + taker_fee_rate())
    net_edge = guaranteed_payout - net_cost
    net_edge_bps = _bps(net_edge / total_cost) if total_cost > 0 else 0

    return Opportunity(
        id=_opp_id(event.slug, "negrisk", int(time.time() * 1000)),
        type=OpportunityType.NEGRISK_REBALANCE,
        event_slug=event.slug,
        legs=legs,
        total_cost=total_cost,
        guaranteed_payout=guaranteed_payout,
        gross_edge=gross_edge,
        net_edge=net_edge,
        net_edge_bps=net_edge_bps,
        detected_at=time.time(),
        expires_at=time.time() + 60,
        metadata={
            "n_outcomes": n,
            "sum_yes_asks": sum_yes_asks,
            "sum_yes_bids": sum_yes_bids,
            "path": "buy_all_yes" if edge_bps_buy >= edge_bps_sell else "buy_all_no",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Combinatorial arbitrage (cross-market covering portfolio)
# ─────────────────────────────────────────────────────────────────────────────

def _enumerate_atomic_outcomes(event: Event) -> List[AtomicOutcome]:
    """Enumerate all atomic outcomes for an event.

    For an NBA game with moneyline (2 outcomes: home/away) + spread
    (2 outcomes: cover/no-cover) + total (2: over/under), there are
    2 × 2 × 2 = 8 atomic outcomes.

    NB: not all 8 outcomes are physically possible! For example, in NBA:
        If home team wins by 4+, both "home wins" AND "home covers -3.5" are true.
        If home team wins by 1-3, "home wins" AND "home did NOT cover -3.5" are true.
        If home team loses, "away wins" AND "home did NOT cover -3.5" are true.
    So really 3 atomic outcomes for moneyline+spread, not 4.

    For full enumeration including totals, we need point ranges. To keep
    this tractable, we model outcomes as event-logical combinations and
    let the user override with custom feasibility constraints.
    """
    atomic = []

    # Simplified model: enumerate cross-product of binary outcomes on each
    # related market. The feasibility constraints are enforced as LP
    # constraints in the optimizer (see optimizer.py).

    moneylines = event.moneyline_markets
    spreads = event.spread_markets
    totals = event.total_markets

    # Each "atomic outcome" is a combination of which side wins each market
    ml_options = []
    for m in moneylines:
        ml_options.append([(m.condition_id, "YES"), (m.condition_id, "NO")])

    sp_options = []
    for m in spreads:
        sp_options.append([(m.condition_id, "YES"), (m.condition_id, "NO")])

    tot_options = []
    for m in totals:
        tot_options.append([(m.condition_id, "YES"), (m.condition_id, "NO")])

    # Cross product
    all_options = ml_options + sp_options + tot_options
    if not all_options:
        return []

    from itertools import product
    for combo in product(*all_options):
        outcomes = dict(combo)
        label = ", ".join(f"{cid[:8]}:{res}" for cid, res in combo)
        atomic.append(AtomicOutcome(label=label, outcomes=outcomes))

    return atomic


def detect_combinatorial_arb(
    event: Event,
    cfg: Config,
) -> List[Opportunity]:
    """Detect combinatorial arbitrage across markets on the same event.

    This is the "real edge" per the article's framing — but in sports the
    combinatorial opportunities are rarer than single-market ones. The
    detection delegates to the LP solver in optimizer.py.

    Strategy: enumerate atomic outcomes, build a payoff matrix where
    rows = atomic outcomes, cols = (market, side) pairs, then solve:

        min   Σ c_i * x_i
        s.t.  Σ A[j,i] * x_i ≥ 1  for each atomic outcome j
              x_i ≥ 0

    If the optimal cost < $1 - fee_buffer, we have a guaranteed-profit
    covering portfolio.
    """
    # Lazy import to avoid hard dependency if PuLP not installed
    try:
        from optimizer import solve_covering_lp
    except ImportError:
        log.warning("optimizer.py not available; skipping combinatorial detector")
        return []

    # Need at least 2 different market categories on the same event
    categories_present = {m.category for m in event.markets if m.book}
    if len(categories_present) < 2:
        return []

    atomic_outcomes = _enumerate_atomic_outcomes(event)
    if not atomic_outcomes:
        return []

    # Only include markets with order books
    markets_with_books = [m for m in event.markets if m.book and m.book.best_ask]
    if len(markets_with_books) < 2:
        return []

    opps = []
    result = solve_covering_lp(
        markets=markets_with_books,
        atomic_outcomes=atomic_outcomes,
        cfg=cfg,
    )

    if result is None:
        return []

    cost, share_allocation = result
    if cost >= 1.0 - taker_fee_rate() * 2:  # no edge after fees
        return []

    net_edge = 1.0 - cost
    edge_bps = _bps(net_edge / cost) if cost > 0 else 0
    if edge_bps < cfg.scanner.min_edge_taker_bps:
        return []

    legs = []
    for (mkt, side), shares in share_allocation.items():
        if shares < 1:  # dust
            continue
        price = mkt.book.best_ask.price if side == Side.YES else (1 - mkt.book.best_bid.price)
        legs.append(Leg(
            market=mkt, side=side, price=price, shares=shares,
            cost=price * shares, is_maker=False,
        ))

    if not legs:
        return []

    total_cost = sum(l.cost for l in legs)
    net_cost = total_cost * (1 + taker_fee_rate())
    net_edge = 1.0 - net_cost  # portfolio pays $1 in every outcome
    net_edge_bps = _bps(net_edge / total_cost) if total_cost > 0 else 0

    opp = Opportunity(
        id=_opp_id(event.slug, "combo", int(time.time() * 1000)),
        type=OpportunityType.COMBINATORIAL,
        event_slug=event.slug,
        legs=legs,
        total_cost=total_cost,
        guaranteed_payout=1.0,  # normalized per share
        gross_edge=1.0 - total_cost,
        net_edge=net_edge,
        net_edge_bps=net_edge_bps,
        detected_at=time.time(),
        expires_at=time.time() + 45,
        metadata={
            "n_atomic_outcomes": len(atomic_outcomes),
            "n_markets_used": len(legs),
            "lp_cost": cost,
        },
    )
    opps.append(opp)
    return opps


# ─────────────────────────────────────────────────────────────────────────────
# 4. Cross-platform arbitrage (Polymarket vs sportsbook)
# ─────────────────────────────────────────────────────────────────────────────

def detect_cross_platform_arb(
    market: Market,
    external_implied_prob: float,
    cfg: Config,
) -> Optional[Opportunity]:
    """Detect arb between Polymarket and a traditional sportsbook.

    Args:
        market: Polymarket market with current book
        external_implied_prob: the sportsbook's implied probability (after removing vig)
            e.g. decimal_odds 2.0 → implied 0.5; -110 American → implied 0.524

    Strategy: if Polymarket YES price < external_implied - margin, buy YES on Poly.
              if Polymarket NO price < (1 - external_implied) - margin, buy NO on Poly.
    Settlement: both platforms resolve to the same outcome.

    Risk: settlement timing differs (Polymarket resolves via UMA oracle;
          sportsbook grades within hours). Capital is locked on the losing
          side until both settle.
    """
    if not market.book or not market.book.best_ask:
        return None

    yes_price = market.book.best_ask.price
    no_price = 1.0 - market.book.best_bid.price

    # Edge = external probability - Poly price (we're long the cheap side)
    edge_yes = external_implied_prob - yes_price
    edge_no = (1 - external_implied_prob) - no_price

    # Need to clear taker fee on the Poly side + sportsbook vig on the other side
    # Sportsbook vig varies; assume 4.5% hold (typical Pinnacle on NBA spread)
    sportsbook_vig = 0.045
    fee_buffer = taker_fee_rate() + sportsbook_vig

    best_edge = max(edge_yes, edge_no)
    if best_edge < fee_buffer + cfg.scanner.min_edge_taker_bps / 10_000:
        return None

    side = Side.YES if edge_yes > edge_no else Side.NO
    price = yes_price if side == Side.YES else no_price

    shares = min(
        cfg.risk.max_position_usdc / price,
        market.book.best_ask.size if side == Side.YES else market.book.best_bid.size,
    )
    if shares < 10:
        return None

    leg = Leg(
        market=market, side=side, price=price, shares=shares,
        cost=price * shares, is_maker=False,
    )
    total_cost = leg.cost
    # Expected payout uses external prob as "true" prob
    expected_payout = (external_implied_prob if side == Side.YES else (1 - external_implied_prob)) * shares
    net_cost = total_cost * (1 + taker_fee_rate())
    net_edge = expected_payout - net_cost
    net_edge_bps = _bps(net_edge / total_cost) if total_cost > 0 else 0

    return Opportunity(
        id=_opp_id(market.condition_id, "xplat", int(time.time() * 1000)),
        type=OpportunityType.CROSS_PLATFORM,
        event_slug=market.event_slug,
        legs=[leg],
        total_cost=total_cost,
        guaranteed_payout=expected_payout,  # not guaranteed — expected
        gross_edge=expected_payout - total_cost,
        net_edge=net_edge,
        net_edge_bps=net_edge_bps,
        detected_at=time.time(),
        expires_at=time.time() + 120,  # sportsbooks move slower, 2min window
        metadata={
            "external_implied_prob": external_implied_prob,
            "sportsbook_vig": sportsbook_vig,
            "side": side.value,
            "settlement_risk": "asynchronous",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# Driver: scan all opportunities on one event
# ─────────────────────────────────────────────────────────────────────────────

def scan_event_for_opportunities(
    event: Event,
    cfg: Config,
) -> List[Opportunity]:
    """Run all detectors on one event. Returns sorted by edge (desc)."""
    opps: List[Opportunity] = []

    # Single-market on each binary market
    for m in event.markets:
        if m.market_type != MarketType.BINARY:
            continue
        opp = detect_single_market_arb(m, cfg)
        if opp:
            opps.append(opp)

    # NegRisk rebalance (whole event)
    nr_opp = detect_negrisk_rebalance_arb(event, cfg)
    if nr_opp:
        opps.append(nr_opp)

    # Combinatorial cross-market
    combo_opps = detect_combinatorial_arb(event, cfg)
    opps.extend(combo_opps)

    # Sort by net edge bps descending
    opps.sort(key=lambda o: o.net_edge_bps, reverse=True)
    return opps
