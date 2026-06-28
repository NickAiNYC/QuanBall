"""
models.py — Domain models for the arbitrage scanner.

Pure dataclasses. No I/O. No external dependencies beyond stdlib.
All other modules import from here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────

class Side(str, Enum):
    YES = "YES"
    NO = "NO"


class MarketType(str, Enum):
    BINARY = "BINARY"                # standard 2-outcome market
    NEGRISK_MULTI = "NEGRISK_MULTI"  # multi-outcome NegRisk market


class Sport(str, Enum):
    NBA = "NBA"
    NFL = "NFL"
    MLB = "MLB"
    NHL = "NHL"
    SOCCER = "SOCCER"
    TENNIS = "TENNIS"
    MMA = "MMA"
    OTHER = "OTHER"


class MarketCategory(str, Enum):
    MONEYLINE = "MONEYLINE"
    SPREAD = "SPREAD"
    TOTAL = "TOTAL"
    PLAYER_PROP = "PLAYER_PROP"
    GAME_PROP = "GAME_PROP"
    QUARTER_LINE = "QUARTER_LINE"
    HALF_LINE = "HALF_LINE"
    OTHER = "OTHER"


class OpportunityType(str, Enum):
    SINGLE_MARKET = "SINGLE_MARKET"        # YES + NO of one market sum < $1
    NEGRISK_REBALANCE = "NEGRISK_REBALANCE"  # sum of all YESes drifts off $1
    COMBINATORIAL = "COMBINATORIAL"          # cross-market covering portfolio
    CROSS_PLATFORM = "CROSS_PLATFORM"        # Polymarket vs sportsbook


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


# ─────────────────────────────────────────────────────────────────────────────
# Core market data
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class OrderBookLevel:
    """One price level in the order book."""
    price: float    # 0..1, in dollars
    size: float     # shares available at this level


@dataclass
class OrderBook:
    """Snapshot of a CLOB order book for one market."""
    bids: List[OrderBookLevel] = field(default_factory=list)  # YES buyers
    asks: List[OrderBookLevel] = field(default_factory=list)  # YES sellers
    timestamp: float = 0.0

    @property
    def best_bid(self) -> Optional[OrderBookLevel]:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> Optional[OrderBookLevel]:
        return self.asks[0] if self.asks else None

    @property
    def mid(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return (self.best_bid.price + self.best_ask.price) / 2
        return None

    @property
    def spread(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return self.best_ask.price - self.best_bid.price
        return None

    def depth_usd(self, levels: int = 5) -> Tuple[float, float]:
        """Return (bid_depth_usd, ask_depth_usd) for top N levels."""
        bid_depth = sum(l.price * l.size for l in self.bids[:levels])
        ask_depth = sum(l.price * l.size for l in self.asks[:levels])
        return bid_depth, ask_depth

    def simulate_buy_yes(self, shares: float) -> Tuple[float, float]:
        """Simulate buying `shares` of YES at market (taker).
        Returns (avg_price, total_cost). Walks the ask side.
        """
        remaining = shares
        total_cost = 0.0
        for level in self.asks:
            take = min(remaining, level.size)
            total_cost += take * level.price
            remaining -= take
            if remaining <= 1e-9:
                break
        filled = shares - remaining
        avg = total_cost / filled if filled > 0 else 0.0
        return avg, total_cost

    def simulate_sell_yes(self, shares: float) -> Tuple[float, float]:
        """Simulate selling `shares` of YES at market (taker).
        Returns (avg_price, total_proceeds). Walks the bid side.
        """
        remaining = shares
        total_proceeds = 0.0
        for level in self.bids:
            take = min(remaining, level.size)
            total_proceeds += take * level.price
            remaining -= take
            if remaining <= 1e-9:
                break
        filled = shares - remaining
        avg = total_proceeds / filled if filled > 0 else 0.0
        return avg, total_proceeds

    def simulate_buy_no(self, shares: float) -> Tuple[float, float]:
        """Buy NO = (1 - YES_price). Walk the bid side as NO asks.
        For Polymarket CLOB: NO ask price ≈ 1 - YES bid price.
        """
        remaining = shares
        total_cost = 0.0
        for level in self.bids:
            no_price = 1.0 - level.price
            take = min(remaining, level.size)
            total_cost += take * no_price
            remaining -= take
            if remaining <= 1e-9:
                break
        filled = shares - remaining
        avg = total_cost / filled if filled > 0 else 0.0
        return avg, total_cost


@dataclass
class Market:
    """A single Polymarket condition (one binary question)."""
    condition_id: str
    question: str
    slug: str
    event_slug: str               # groups related markets (e.g. one NBA game)
    token_id_yes: str
    token_id_no: str
    market_type: MarketType
    sport: Sport = Sport.OTHER
    category: MarketCategory = MarketCategory.OTHER
    end_date: Optional[datetime] = None
    neg_risk: bool = False
    neg_risk_request_id: Optional[str] = None
    neg_risk_market_id: Optional[str] = None

    # Live state (updated by scanner)
    book: Optional[OrderBook] = None
    last_price_yes: Optional[float] = None  # last traded price
    last_update_ts: float = 0.0

    # Parsed structured fields (for combinatorial logic)
    team_home: Optional[str] = None
    team_away: Optional[str] = None
    spread_value: Optional[float] = None      # e.g. -3.5 means home favored by 3.5
    total_value: Optional[float] = None       # e.g. 220.5 for O/U
    player_name: Optional[str] = None
    quarter: Optional[int] = None             # 1-4 for NBA quarters

    @property
    def price_yes(self) -> Optional[float]:
        """Best ask for YES (cost to buy YES)."""
        if self.book and self.book.best_ask:
            return self.book.best_ask.price
        return self.last_price_yes

    @property
    def price_no(self) -> Optional[float]:
        """Cost to buy NO = 1 - best YES bid."""
        if self.book and self.book.best_bid:
            return 1.0 - self.book.best_bid.price
        if self.last_price_yes is not None:
            return 1.0 - self.last_price_yes
        return None

    @property
    def is_in_play(self) -> bool:
        """Heuristic: spread < 1 cent suggests live trading."""
        if self.book and self.book.spread is not None:
            return self.book.spread < 0.01
        return False


@dataclass
class Event:
    """A Polymarket event = a single sports game (typically)."""
    slug: str
    title: str
    sport: Sport
    start_time: Optional[datetime]
    markets: List[Market] = field(default_factory=list)

    @property
    def moneyline_markets(self) -> List[Market]:
        return [m for m in self.markets if m.category == MarketCategory.MONEYLINE]

    @property
    def spread_markets(self) -> List[Market]:
        return [m for m in self.markets if m.category == MarketCategory.SPREAD]

    @property
    def total_markets(self) -> List[Market]:
        return [m for m in self.markets if m.category == MarketCategory.TOTAL]


# ─────────────────────────────────────────────────────────────────────────────
# Opportunities
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Leg:
    """One side of an arbitrage opportunity."""
    market: Market
    side: Side                    # buy YES or buy NO
    price: float                  # expected fill price
    shares: float                 # number of shares to buy
    cost: float                   # price * shares
    is_maker: bool = False        # resting limit order vs crossing


@dataclass
class Opportunity:
    """A detected arbitrage opportunity."""
    id: str                       # uuid or hash
    type: OpportunityType
    event_slug: str
    legs: List[Leg]
    total_cost: float             # sum of leg costs
    guaranteed_payout: float      # min payout across all outcomes
    gross_edge: float             # guaranteed_payout - total_cost
    net_edge: float               # after fees
    net_edge_bps: float           # net_edge / total_cost * 10_000
    detected_at: float            # unix ts
    expires_at: Optional[float] = None  # when opportunity likely vanishes
    metadata: Dict = field(default_factory=dict)

    @property
    def profit_pct(self) -> float:
        return self.gross_edge / self.total_cost if self.total_cost > 0 else 0.0


@dataclass
class Position:
    """An executed or pending position."""
    opportunity_id: str
    legs: List[Leg]
    filled_shares: List[float]    # actual fills per leg
    avg_fill_prices: List[float]
    total_cost: float
    status: OrderStatus = OrderStatus.PENDING
    opened_at: float = 0.0
    closed_at: Optional[float] = None
    realized_pnl: Optional[float] = None


# ─────────────────────────────────────────────────────────────────────────────
# Atomic outcomes (for combinatorial arb)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AtomicOutcome:
    """A fully-specified outcome across all related markets on one event.

    Example for an NBA game with moneyline + spread + total:
        AtomicOutcome(
            label="LAL win; LAL -3.5; O 220.5",
            outcomes={
                "moneyline": "LAL",       # which team wins outright
                "spread": "LAL_COVER",    # did home team cover?
                "total": "OVER"           # did total go over?
            }
        )
    """
    label: str
    outcomes: Dict[str, str]      # market_category -> result


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
