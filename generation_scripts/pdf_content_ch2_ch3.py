"""
pdf_content_ch2_ch3.py — Chapter 2 (Data & Market Discovery) and Chapter 3 (Scanner Implementation).
"""
from pdf_helpers import (
    h1, h2, h3, h4, body, bullet, numbered, kicker, math_block,
    callout, warning, info, key_insight, code_block, std_table, caption,
    hr, soft_break, chapter_break, ACCENT_EMERALD, ACCENT_AMBER,
)
from reportlab.platypus import Paragraph, Spacer


# ─────────────────────────────────────────────────────────────────────────────
# CHAPTER 2 — Data & Market Discovery
# ─────────────────────────────────────────────────────────────────────────────

def chapter_2():
    s = []
    s.append(kicker("Chapter 2 · Data Pipeline"))
    s.append(h1("Data & Market Discovery"))
    s.append(body(
        "An arbitrage scanner is only as good as its data feed. This chapter "
        "covers the Polymarket API stack end-to-end: the Gamma API for event "
        "and market metadata, the CLOB REST API for order book snapshots, "
        "and the CLOB WebSocket for real-time book deltas. We then cover how "
        "to group related markets by event, how to detect the logical "
        "dependencies between moneyline, spread, and totals markets that "
        "make combinatorial arbitrage possible, and how to model liquidity "
        "and slippage from the order book. Every code snippet in this "
        "chapter is taken directly from the production modules in the "
        "companion package."
    ))

    s.append(h2("2.1  The Polymarket API stack"))
    s.append(body(
        "Polymarket exposes three distinct API surfaces, each with a "
        "specific role. Understanding which API to use for which task is "
        "the first step in building a low-latency scanner."
    ))

    rows = [
        ["Gamma API", "gamma-api.polymarket.com", "HTTPS REST", "Event metadata, market questions, slugs, tags, resolution criteria"],
        ["CLOB REST", "clob.polymarket.com", "HTTPS REST", "Order books, prices, last trades, order placement (auth)"],
        ["CLOB WebSocket", "wss://ws-subscriptions-clob.polymarket.com/ws", "WebSocket", "Real-time book deltas, last-trade prices, order fill notifications"],
        ["Polygon RPC", "polygon-rpc.com", "JSON-RPC", "On-chain reads (ERC-1155 balances, condition resolution)"],
    ]
    s.append(std_table(
        ["API", "Base URL", "Transport", "Use for"],
        rows,
        col_ratios=[0.16, 0.30, 0.16, 0.38],
    ))
    s.append(caption("Table 2.1 — Polymarket API surfaces and their roles"))

    s.append(body(
        "The Gamma API is the public metadata layer. It returns event "
        "listings, market questions, slugs, tags, and resolution criteria "
        "as JSON. It does not have order book data — that lives on the "
        "CLOB. The CLOB REST API is where prices live: it exposes "
        "<code>/book?token_id=...</code> for full order book snapshots, "
        "<code>/price?token_id=...&side=buy|sell|mid</code> for "
        "top-of-book quotes, and authenticated endpoints for order "
        "placement. The CLOB WebSocket pushes real-time book deltas so "
        "you do not have to poll."
    ))

    s.append(h2("2.2  Fetching events and markets"))
    s.append(body(
        "The Gamma <code>/events</code> endpoint lists all active events "
        "with optional filters. Each event contains a list of markets. "
        "For sports arbitrage, we want to filter to sports-tagged events "
        "resolving within the next 12 hours (the daily sports cadence). "
        "Polymarket's tag filter is unreliable, so we apply client-side "
        "sport detection via regex on the event title and explicit tag "
        "labels."
    ))

    s.append(h3("Sport detection"))
    s.append(body(
        "The <code>detect_sport()</code> function in "
        "<code>gamma_client.py</code> checks the event's tags first "
        "(Polymarket sometimes tags Sports → NBA), then falls back to a "
        "regex match against the event title using team-name patterns. "
        "The regex dictionary covers the major NBA, NFL, MLB, NHL, "
        "soccer, tennis, and MMA team and league keywords. Events that "
        "match no pattern are classified as <code>OTHER</code> and "
        "filtered out of the sports scanner."
    ))

    s.extend(code_block(
'''# From gamma_client.py — sport detection by regex fallback
_SPORT_PATTERNS: Dict[Sport, re.Pattern] = {
    Sport.NBA: re.compile(
        r"\\b(NBA|Lakers|Celtics|Warriors|Nuggets|Bucks|Suns|Knicks|"
        r"76ers|Heat|Mavericks|Clippers|Kings|Hawks|Pacers|Bulls|"
        r"Cavaliers|Magic|Pistons|Raptors|Grizzlies|Pelicans|"
        r"Timberwolves|Spurs|Rockets|Thunder|Trail Blazers|Blazers|"
        r"Jazz|Nets)\\b",
        re.IGNORECASE,
    ),
    Sport.NFL: re.compile(
        r"\\b(NFL|Chiefs|Eagles|49ers|Bills|Cowboys|Ravens|Bengals|"
        r"Packers|Lions|Dolphins|Jets|Patriots|Steelers|Browns|"
        r"Texans|Colts|Jaguars|Titans|Broncos|Raiders|Chargers|"
        r"Seahawks|Rams|Cardinals|Falcons|Panthers|Saints|Buccaneers|"
        r"Vikings|Bears|Commanders|Giants)\\b",
        re.IGNORECASE,
    ),
    # ... MLB, NHL, SOCCER, TENNIS, MMA ...
}

def detect_sport(title: str, tags: Optional[List[str]] = None) -> Sport:
    """Detect sport from event title and tags."""
    if tags:
        for tag in tags:
            t = tag.lower()
            if "nba" in t: return Sport.NBA
            if "nfl" in t: return Sport.NFL
            # ... etc
    for sport, pattern in _SPORT_PATTERNS.items():
        if pattern.search(title):
            return sport
    return Sport.OTHER''',
        label="gamma_client.py — sport detection"
    ))

    s.append(h3("Fetching events in parallel"))
    s.append(body(
        "The <code>fetch_sports_events_with_markets()</code> method lists "
        "sports events, then fetches full event details (including all "
        "markets) in parallel using <code>asyncio.gather</code>. This is "
        "critical for latency: a sequential fetch of 50 events at 200ms "
        "each would take 10 seconds, but a parallel fetch with a "
        "16-connection pool completes in under a second."
    ))

    s.extend(code_block(
'''# From gamma_client.py — parallel event fetching
async def fetch_sports_events_with_markets(
    self,
    sports: Optional[List[Sport]] = None,
    max_events: int = 50,
) -> List[Event]:
    raw_events = await self.list_sports_events(limit=max_events)
    if sports:
        sports_set = set(sports)
        raw_events = [
            ev for ev in raw_events
            if detect_sport(
                ev.get("title", ""),
                [t.get("label", "") for t in ev.get("tags", [])],
            ) in sports_set
        ]

    slugs = [ev.get("slug") for ev in raw_events if ev.get("slug")]
    detailed = await asyncio.gather(
        *[self.get_event(s) for s in slugs],
        return_exceptions=True,
    )

    events = []
    for raw in detailed:
        if isinstance(raw, Exception) or raw is None:
            continue
        try:
            events.append(self.parse_event(raw))
        except Exception as e:
            log.warning(f"Failed to parse event: {e}")
    return events''',
        label="gamma_client.py — parallel event fetching"
    ))

    s.append(h2("2.3  Logical dependency detection"))
    s.append(body(
        "Combinatorial arbitrage requires identifying which markets on the "
        "same event are logically dependent — that is, which markets share "
        "the same underlying outcome. For NBA games, this typically means "
        "the moneyline, the spread, the totals, and any player props on "
        "the same game. The <code>detect_category()</code> function "
        "classifies each market by regex-matching its question text against "
        "patterns for moneyline, spread, total, and player prop phrasings."
    ))

    s.extend(code_block(
'''# From gamma_client.py — market category detection
_MONEYLINE_RE = re.compile(
    r"\\b(will\\s+win|moneyline|match\\s+winner|game\\s+winner)\\b",
    re.IGNORECASE,
)
_SPREAD_RE = re.compile(
    r"([+-]?\\d+\\.?\\d*)\\s*(point|pt|run|puck|goal)\\s*"
    r"(spread|line|handicap)|"
    r"\\b(spread|handicap|line)\\b\\s*([+-]?\\d+\\.?\\d*)",
    re.IGNORECASE,
)
_TOTAL_RE = re.compile(
    r"(over|under|o/u)\\s*(\\d+\\.?\\d*)|"
    r"(total|totals)\\s*(over|under|o/u)?\\s*(\\d+\\.?\\d*)",
    re.IGNORECASE,
)
_PLAYER_PROP_RE = re.compile(
    r"\\b(points|rebounds|assists|steals|blocks|threes|3-pointers|"
    r"passing\\s+yards|rushing\\s+yards|receiving\\s+yards|"
    r"touchdowns|hits|home\\s+runs|strikeouts|"
    r"goals|assists|saves)\\b.*\\b(over|under|o/u)\\b",
    re.IGNORECASE,
)

def detect_category(question: str) -> MarketCategory:
    if _PLAYER_PROP_RE.search(question):
        return MarketCategory.PLAYER_PROP
    if _SPREAD_RE.search(question):
        return MarketCategory.SPREAD
    if _TOTAL_RE.search(question):
        return MarketCategory.TOTAL
    if _MONEYLINE_RE.search(question):
        return MarketCategory.MONEYLINE
    return MarketCategory.OTHER''',
        label="gamma_client.py — market category detection"
    ))

    s.append(body(
        "The <code>parse_market()</code> method also extracts structured "
        "fields: <code>spread_value</code> from spread questions (e.g., "
        "−3.5 from <i>Lakers −3.5</i>), <code>total_value</code> from "
        "totals questions (e.g., 220.5 from <i>Over 220.5</i>), and "
        "<code>team_home</code> / <code>team_away</code> for downstream "
        "feasibility constraints in the LP solver."
    ))

    s.extend(info(
        "For markets that do not match any regex pattern (rare but possible "
        "for novel prop types), the scanner falls back to classifying them "
        "as <code>OTHER</code> and excluding them from combinatorial "
        "detection. A production system should periodically audit these "
        "OTHER markets and add new regex patterns as new market types "
        "appear on Polymarket."
    ))

    s.append(h2("2.4  Real-time data: polling vs WebSocket"))
    s.append(body(
        "Two transport modes are supported, chosen by scan context. For "
        "pre-game scanning (the bulk of opportunities), a 5-second polling "
        "interval on the CLOB REST API is sufficient because prices move "
        "slowly when no game is in progress. For in-play scanning (the "
        "highest-edge windows during live games), the WebSocket "
        "subscription is mandatory — sub-second price updates are required "
        "to catch the lag between a scoring play and the order book "
        "re-pricing."
    ))

    rows = [
        ["Pre-game (idle)", "5-10 sec", "REST /book?token_id=", "Lower API load, sufficient for slow-moving books"],
        ["Pre-game (active)", "2-3 sec", "REST /book?token_id=", "Tighter polling near tipoff when books active"],
        ["In-play", "Real-time push", "WebSocket subscribe", "Sub-second deltas, required for live edges"],
        ["Post-game (resolution)", "30 sec", "REST /markets?id=", "Watch for UMA dispute window"],
    ]
    s.append(std_table(
        ["Scan context", "Poll interval", "Transport", "Rationale"],
        rows,
        col_ratios=[0.22, 0.16, 0.22, 0.40],
    ))
    s.append(caption("Table 2.2 — Polling strategy by scan context"))

    s.append(h3("WebSocket subscription and reconnection"))
    s.append(body(
        "The <code>CLOBWSClient</code> class in <code>clob_client.py</code> "
        "manages a persistent WebSocket connection with automatic "
        "reconnection. The subscribe message takes a list of token IDs and "
        "a type field (\"market\" for book updates, \"last_trade_price\" "
        "for trade ticks). On disconnect, the client reconnects with "
        "exponential backoff: 1s, 2s, 5s, 10s, 30s, 60s. A handler "
        "callback is invoked for every book update, allowing downstream "
        "detectors to react in real time."
    ))

    s.extend(code_block(
'''# From clob_client.py — WebSocket client with auto-reconnect
class CLOBWSClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.url = cfg.api.ws_url
        self.ws: Optional[Any] = None
        self._books: Dict[str, OrderBook] = {}
        self._handlers: List[callable] = []
        self._running = False
        self._reconnect_attempts = 0

    def on_book_update(self, handler):
        """Register a callback: handler(token_id: str, book: OrderBook)."""
        self._handlers.append(handler)

    async def run(self, token_ids: List[str]):
        """Connect, subscribe, and pump messages until stopped."""
        import websockets
        self._running = True
        while self._running:
            try:
                async with websockets.connect(
                    self.url, ping_interval=20, ping_timeout=10,
                ) as ws:
                    self.ws = ws
                    self._reconnect_attempts = 0
                    await self.subscribe(token_ids)
                    async for raw_msg in ws:
                        if not self._running: break
                        await self._handle_message(raw_msg)
            except Exception as e:
                if not self._running: break
                self._reconnect_attempts += 1
                backoff = self._backoff()
                log.warning(
                    f"CLOB WS disconnected (attempt "
                    f"{self._reconnect_attempts}): {e}; reconnect in {backoff}s"
                )
                await asyncio.sleep(backoff)

    def _backoff(self) -> float:
        backoffs = self.cfg.scanner.ws_reconnect_backoff
        idx = min(self._reconnect_attempts - 1, len(backoffs) - 1)
        return backoffs[idx]''',
        label="clob_client.py — WebSocket client"
    ))

    s.append(h2("2.5  Liquidity and depth analysis"))
    s.append(body(
        "Detecting an arbitrage edge is only half the battle — you also "
        "need to know how much you can actually fill without moving the "
        "market. The <code>OrderBook</code> dataclass in "
        "<code>models.py</code> provides several methods for depth-aware "
        "fill simulation."
    ))

    s.append(h3("Depth-weighted fill simulation"))
    s.append(body(
        "The <code>simulate_buy_yes(shares)</code> method walks the ask "
        "side of the book, consuming levels until the requested share "
        "count is filled. It returns the volume-weighted average price "
        "(VWAP) and the total cost. This is the same logic the detector "
        "uses to compute realistic slippage for a target notional."
    ))

    s.extend(code_block(
'''# From models.py — order book depth simulation
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

def depth_usd(self, levels: int = 5) -> Tuple[float, float]:
    """Return (bid_depth_usd, ask_depth_usd) for top N levels."""
    bid_depth = sum(l.price * l.size for l in self.bids[:levels])
    ask_depth = sum(l.price * l.size for l in self.asks[:levels])
    return bid_depth, ask_depth''',
        label="models.py — depth simulation"
    ))

    s.append(h3("Slippage estimation"))
    s.append(body(
        "The <code>estimate_slippage_bps()</code> function in "
        "<code>risk.py</code> computes the expected slippage in basis "
        "points for a target notional. It compares the VWAP from "
        "<code>simulate_buy_yes()</code> against the best ask, and "
        "returns the percentage difference. The risk gate rejects "
        "opportunities where estimated slippage exceeds "
        "<code>cfg.risk.max_slippage_bps</code> (default 50 bps)."
    ))

    s.extend(code_block(
'''# From risk.py — slippage estimation
def estimate_slippage_bps(book, target_notional_usdc: float, cfg: Config) -> float:
    """Estimate slippage in bps for a market order of given size."""
    if not book or not book.best_ask:
        return float("inf")
    shares_needed = target_notional_usdc / book.best_ask.price
    avg_price, _ = book.simulate_buy_yes(shares_needed)
    if avg_price <= 0:
        return float("inf")
    slippage_fraction = (avg_price - book.best_ask.price) / book.best_ask.price
    return slippage_fraction * 10_000''',
        label="risk.py — slippage estimation"
    ))

    s.append(h2("2.6  Rate limiting and concurrency"))
    s.append(body(
        "Polymarket's CLOB API has a soft rate limit of approximately 10 "
        "requests per second per IP. The scanner respects this via two "
        "mechanisms: <code>httpx.Limits</code> caps concurrent "
        "connections, and a <code>asyncio.Semaphore</code> in "
        "<code>get_books_for_markets()</code> caps concurrent book fetches "
        "to 16 (configurable via <code>cfg.api.max_concurrent_requests</code>)."
    ))
    s.append(body(
        "For higher-throughput scanning, you can shard by event slug and "
        "distribute across multiple VPS instances, each with its own IP. "
        "The Polygon RPC endpoint can also be load-balanced across "
        "Alchemy/Infura/QuickNode for on-chain reads. Chapter 4 covers "
        "the scaling architecture in detail."
    ))

    s.append(h2("2.7  Caching and snapshot persistence"))
    s.append(body(
        "Every scan cycle produces a snapshot of all market states at that "
        "instant. The <code>backtest.py</code> module's "
        "<code>record_snapshots()</code> function serializes these "
        "snapshots to JSON for later backtesting. Each snapshot contains "
        "the timestamp, the full event tree, and the top 10 levels of "
        "each market's order book. A typical 6-hour recording at 30-second "
        "intervals produces about 720 snapshots totaling 200-500 MB of "
        "JSON, depending on the number of active sports events."
    ))
    s.append(body(
        "For production monitoring, snapshots should also be written to a "
        "time-series database (TimescaleDB, InfluxDB, or ClickHouse) for "
        "queryable historical analysis. The companion code ships with "
        "JSON-only persistence for simplicity; production deployments "
        "should swap in a proper TSDB."
    ))

    s.append(chapter_break())
    return s


# ─────────────────────────────────────────────────────────────────────────────
# CHAPTER 3 — Full Arbitrage Scanner Implementation
# ─────────────────────────────────────────────────────────────────────────────

def chapter_3():
    s = []
    s.append(kicker("Chapter 3 · Implementation"))
    s.append(h1("Arbitrage Scanner: Full Implementation"))
    s.append(body(
        "This chapter walks through the complete production scanner, "
        "module by module. The accompanying Python package contains twelve "
        "runnable files totaling roughly 2,500 lines of code. Each section "
        "below explains the design decisions, presents the key code "
        "listings, and connects the module to the math developed in "
        "Chapter 1. By the end of this chapter you should be able to "
        "install the package, set your API credentials, and run the "
        "scanner in dry-run mode against live Polymarket data."
    ))

    s.append(h2("3.1  System architecture"))
    s.append(body(
        "The scanner is built as an async pipeline with five stages: data "
        "ingestion, opportunity detection, risk gating, execution, and "
        "position tracking. Each stage is a separate module with a clean "
        "interface, allowing individual components to be tested, "
        "replaced, or scaled independently."
    ))

    rows = [
        ["1. Ingestion", "gamma_client.py, clob_client.py", "Fetch events, markets, order books (parallel)"],
        ["2. Detection", "detectors.py, optimizer.py", "Run 4 arbitrage detectors per event"],
        ["3. Risk gate", "risk.py", "Kelly sizing, exposure caps, blacklist, slippage check"],
        ["4. Execution", "executor.py", "Concurrent leg placement, partial-fill hedging, rollback"],
        ["5. Tracking", "scanner.py (Scanner class)", "Position state, PnL, alerts, persistence"],
    ]
    s.append(std_table(
        ["Stage", "Module(s)", "Responsibility"],
        rows,
        col_ratios=[0.20, 0.32, 0.48],
    ))
    s.append(caption("Table 3.1 — Scanner pipeline stages"))

    s.append(body(
        "The pipeline runs in a single async event loop. Stage 1 fans out "
        "across events using <code>asyncio.gather</code>; stage 2 runs "
        "synchronously on the resolved data; stage 3 is a pure function "
        "with no I/O; stage 4 fans out across legs of an opportunity; "
        "stage 5 updates in-memory state. The loop sleeps "
        "<code>cfg.scanner.poll_interval_sec</code> seconds between cycles "
        "(default 5 seconds for sports)."
    ))

    s.append(h2("3.2  Configuration module"))
    s.append(body(
        "All runtime knobs live in <code>config.py</code> as a hierarchy "
        "of dataclasses: <code>ApiConfig</code>, <code>ScannerConfig</code>, "
        "<code>RiskConfig</code>, <code>ExecutionConfig</code>, "
        "<code>AlertsConfig</code>. Configuration is loaded in three "
        "layers: code defaults, then environment variables (POLY_* prefix), "
        "then optional YAML file. This makes it easy to run the scanner "
        "with different configurations across environments (dev, staging, "
        "production) without code changes."
    ))

    s.extend(code_block(
'''# From config.py — configuration dataclasses
@dataclass
class ScannerConfig:
    """Opportunity detection thresholds."""
    min_edge_taker_bps: int = 75          # must clear 0.75% taker fee
    min_edge_maker_bps: int = 30          # maker fee = 0, just slippage buffer
    min_edge_negrisk_bps: int = 100       # NegRisk rebalance needs higher threshold
    min_liquidity_usdc: float = 5_000     # each side must have ≥ this depth
    min_depth_levels: int = 3
    sports_only: bool = True
    resolve_within_hours: int = 12        # daily sports cadence
    poll_interval_sec: float = 5.0
    in_play_poll_interval_sec: float = 1.0
    ws_reconnect_backoff: List[float] = field(
        default_factory=lambda: [1, 2, 5, 10, 30, 60]
    )

@dataclass
class RiskConfig:
    """Position sizing and exposure limits."""
    max_position_usdc: float = 5_000
    max_game_exposure_usdc: float = 15_000
    max_daily_exposure_usdc: float = 100_000
    max_open_positions: int = 25
    kelly_fraction: float = 0.25          # 25% of full Kelly
    kelly_floor_bps: int = 10
    kelly_cap_bps: int = 500              # never more than 5% of bankroll per leg
    bankroll_usdc: float = 50_000
    slippage_bps_per_1k_usdc: float = 5.0
    max_slippage_bps: int = 50''',
        label="config.py — configuration dataclasses"
    ))

    s.append(body(
        "The fee constants are defined at module level for easy reference: "
        "<code>TAKER_FEE_BPS = 75</code> and <code>MAKER_FEE_BPS = 0</code>. "
        "Helper functions <code>taker_fee_rate()</code> and "
        "<code>maker_fee_rate()</code> return these as fractions (0.0075 "
        "and 0.0) for use in detector math."
    ))

    s.append(h2("3.3  Domain models"))
    s.append(body(
        "The <code>models.py</code> module defines the core dataclasses: "
        "<code>Market</code>, <code>OrderBook</code>, <code>Event</code>, "
        "<code>Opportunity</code>, <code>Leg</code>, <code>Position</code>, "
        "and <code>AtomicOutcome</code>. These are pure data containers "
        "with no I/O — they exist to give the rest of the codebase a "
        "shared vocabulary."
    ))

    s.extend(code_block(
'''# From models.py — core domain classes
@dataclass
class OrderBookLevel:
    price: float    # 0..1, in dollars
    size: float     # shares available at this level

@dataclass
class OrderBook:
    bids: List[OrderBookLevel] = field(default_factory=list)
    asks: List[OrderBookLevel] = field(default_factory=list)
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

@dataclass
class Market:
    condition_id: str
    question: str
    slug: str
    event_slug: str
    token_id_yes: str
    token_id_no: str
    market_type: MarketType
    sport: Sport = Sport.OTHER
    category: MarketCategory = MarketCategory.OTHER
    book: Optional[OrderBook] = None
    spread_value: Optional[float] = None
    total_value: Optional[float] = None
    # ... additional fields

    @property
    def price_yes(self) -> Optional[float]:
        if self.book and self.book.best_ask:
            return self.book.best_ask.price
        return None

    @property
    def price_no(self) -> Optional[float]:
        if self.book and self.book.best_bid:
            return 1.0 - self.book.best_bid.price
        return None''',
        label="models.py — core domain classes"
    ))

    s.append(h2("3.4  Single-market YES+NO detector"))
    s.append(body(
        "The <code>detect_single_market_arb()</code> function in "
        "<code>detectors.py</code> is the bread-and-butter detector. It "
        "implements the math from Section 1.3: compute YES ask + NO ask, "
        "check if the sum is below $1 after fees, and if so construct an "
        "<code>Opportunity</code> object with both legs."
    ))

    s.extend(code_block(
'''# From detectors.py — single-market arb detector (simplified)
def detect_single_market_arb(market: Market, cfg: Config) -> Optional[Opportunity]:
    if market.book is None or market.market_type != MarketType.BINARY:
        return None
    book = market.book
    if not book.best_ask or not book.best_bid:
        return None
    if not _liquidity_check(book, cfg.scanner.min_liquidity_usdc):
        return None

    # Taker path: cross both sides
    yes_ask = book.best_ask.price
    no_cost = 1.0 - book.best_bid.price  # buy NO = sell YES at bid
    total_cost_taker = yes_ask + no_cost
    payout_per_share = 1.0
    fee_taker = total_cost_taker * taker_fee_rate()
    net_cost_taker = total_cost_taker + fee_taker
    net_edge_taker = payout_per_share - net_cost_taker
    edge_bps_taker = _bps(net_edge_taker / total_cost_taker)

    # Maker path: rest both sides at mid ± spread/2
    if book.mid is not None:
        spread = book.spread or 0
        maker_total_cost = 1.0 - spread
        maker_edge = spread
        edge_bps_maker = _bps(maker_edge / maker_total_cost)
    else:
        edge_bps_maker = 0

    # Pick better path
    best_edge_bps = max(edge_bps_taker, edge_bps_maker)
    is_maker = edge_bps_maker > edge_bps_taker
    threshold = (cfg.scanner.min_edge_maker_bps if is_maker
                 else cfg.scanner.min_edge_taker_bps)
    if best_edge_bps < threshold:
        return None

    # Size by min of bid/ask depth and position cap
    bid_depth, ask_depth = book.depth_usd(levels=5)
    max_shares_by_depth = min(
        ask_depth / yes_ask if yes_ask > 0 else 0,
        bid_depth / no_cost if no_cost > 0 else 0,
    )
    cost_per_share = total_cost_taker if not is_maker else maker_total_cost
    max_shares_by_position = cfg.risk.max_position_usdc / cost_per_share
    shares = min(max_shares_by_depth, max_shares_by_position)
    if shares < 10:  # dust filter
        return None

    # Build legs and Opportunity
    legs = [
        Leg(market=market, side=Side.YES, price=yes_ask,
            shares=shares, cost=yes_ask * shares, is_maker=is_maker),
        Leg(market=market, side=Side.NO, price=no_cost,
            shares=shares, cost=no_cost * shares, is_maker=is_maker),
    ]
    total_cost = sum(l.cost for l in legs)
    net_cost = total_cost if is_maker else total_cost * (1 + taker_fee_rate())
    guaranteed_payout = shares
    return Opportunity(
        id=_opp_id(market.condition_id, int(time.time() * 1000)),
        type=OpportunityType.SINGLE_MARKET,
        event_slug=market.event_slug,
        legs=legs, total_cost=total_cost,
        guaranteed_payout=guaranteed_payout,
        gross_edge=guaranteed_payout - total_cost,
        net_edge=guaranteed_payout - net_cost,
        net_edge_bps=_bps((guaranteed_payout - net_cost) / total_cost),
        detected_at=time.time(),
        expires_at=time.time() + 30,
    )''',
        label="detectors.py — single-market detector"
    ))

    s.append(h2("3.5  Multi-outcome NegRisk detector"))
    s.append(body(
        "The <code>detect_negrisk_rebalance_arb()</code> function "
        "implements the math from Section 1.4. It iterates over all "
        "NegRisk markets on an event, computes the sum of YES asks and "
        "the sum of YES bids, then checks both the buy-all-YES and "
        "buy-all-NO conditions. Per the article framing, this detector is "
        "mostly relevant for politics — sports NegRisk markets are rare "
        "and thin — but it is included for completeness and for the "
        "occasional MVP or championship winner market that does appear in "
        "sports."
    ))

    s.extend(code_block(
'''# From detectors.py — NegRisk rebalance detector (simplified)
def detect_negrisk_rebalance_arb(event: Event, cfg: Config) -> Optional[Opportunity]:
    neg_markets = [m for m in event.markets if m.neg_risk and m.book]
    if len(neg_markets) < 3:
        return None

    sum_yes_asks = 0.0
    sum_yes_bids = 0.0
    valid_markets = []
    for m in neg_markets:
        if not m.book or not m.book.best_ask or not m.book.best_bid:
            continue
        sum_yes_asks += m.book.best_ask.price
        sum_yes_bids += m.book.best_bid.price
        valid_markets.append(m)

    if len(valid_markets) < 3:
        return None

    # Buy-all-YES arb: sum(asks) < $1
    fee_taker = sum_yes_asks * taker_fee_rate()
    net_cost_buy_all = sum_yes_asks + fee_taker
    edge_buy_all = 1.0 - net_cost_buy_all
    edge_bps_buy = _bps(edge_buy_all / sum_yes_asks)

    # Buy-all-NO arb: sum(bids) > $1
    n = len(valid_markets)
    no_total_cost = n - sum_yes_bids
    no_fee = no_total_cost * taker_fee_rate()
    no_payout = n - 1
    edge_sell_all = no_payout - (no_total_cost + no_fee)
    edge_bps_sell = _bps(edge_sell_all / no_total_cost)

    best_edge_bps = max(edge_bps_buy, edge_bps_sell)
    if best_edge_bps < cfg.scanner.min_edge_negrisk_bps:
        return None

    # Construct legs for whichever path won...
    # (see full implementation in detectors.py)
    return opportunity''',
        label="detectors.py — NegRisk rebalance detector"
    ))

    s.append(h2("3.6  Combinatorial detector and LP solver"))
    s.append(body(
        "The combinatorial detector is the most sophisticated piece of "
        "the scanner. It enumerates all feasible atomic outcomes for an "
        "event, builds a payoff matrix, and solves the covering portfolio "
        "LP using PuLP (an open-source MILP solver). The "
        "<code>solve_covering_lp()</code> function in "
        "<code>optimizer.py</code> implements the LP formulation from "
        "Section 1.5."
    ))

    s.append(h3("Feasibility pruning"))
    s.append(body(
        "The <code>is_feasible_outcome()</code> function prunes physically "
        "impossible atomic outcomes before passing them to the LP solver. "
        "For example, in an NBA game where the home team is favored by "
        "3.5 points, the combination <i>away team wins AND home team "
        "covers −3.5</i> is impossible (if the away team wins, the home "
        "team cannot have covered a negative spread). Pruning these "
        "impossible combinations is critical: without it, the LP would "
        "waste effort covering outcomes that can never occur and might "
        "report a false arbitrage."
    ))

    s.extend(code_block(
'''# From optimizer.py — feasibility pruning
def is_feasible_outcome(outcome: AtomicOutcome, markets: List[Market]) -> bool:
    """Check whether an atomic outcome is physically possible."""
    moneylines = [m for m in markets if m.category == MarketCategory.MONEYLINE]
    spreads = [m for m in markets if m.category == MarketCategory.SPREAD]

    # Find moneyline winner
    ml_winner = None
    for m in moneylines:
        if m.condition_id in outcome.outcomes:
            res = outcome.outcomes[m.condition_id]
            ml_winner = "home" if res == "YES" else "away"

    # Check spread consistency
    for m in spreads:
        if m.condition_id not in outcome.outcomes:
            continue
        spread_res = outcome.outcomes[m.condition_id]
        if m.spread_value is not None:
            home_favored = m.spread_value < 0
            home_covers = spread_res == "YES"
            # If home favored and away wins, home cannot cover
            if home_favored and ml_winner == "away" and home_covers:
                return False
            # If home underdog and home wins, home must cover
            if not home_favored and ml_winner == "home" and not home_covers:
                return False
    return True''',
        label="optimizer.py — feasibility pruning"
    ))

    s.append(h3("LP solver"))
    s.append(body(
        "The LP itself is straightforward PuLP: minimize total cost "
        "subject to coverage constraints. The solver is called with a "
        "5-second time limit; if it does not converge in that window, "
        "the detector skips the event. For very large events (many "
        "markets, many outcomes), the LP can be slow — Chapter 4 covers "
        "scaling strategies including sharding by market category."
    ))

    s.extend(code_block(
'''# From optimizer.py — LP solver
def solve_covering_lp(markets, atomic_outcomes, cfg):
    if not HAS_PULP:
        return None
    feasible = [o for o in atomic_outcomes if is_feasible_outcome(o, markets)]
    if not feasible:
        return None

    # Candidate positions: (YES, NO) for each market
    positions = []
    for m in markets:
        if not m.book: continue
        if m.book.best_ask: positions.append((m, Side.YES))
        if m.book.best_bid: positions.append((m, Side.NO))

    prob = pulp.LpProblem("covering_portfolio", pulp.LpMinimize)
    x = {
        (m.condition_id, s): pulp.LpVariable(
            f"x_{m.condition_id[:8]}_{s.value}", lowBound=0
        )
        for (m, s) in positions
    }

    # Objective: minimize Σ cost * x
    prob += pulp.lpSum(
        _position_cost((m, s)) * x[(m.condition_id, s)]
        for (m, s) in positions
    )

    # Constraints: each atomic outcome covered
    for j, outcome in enumerate(feasible):
        prob += pulp.lpSum(
            (1.0 if _position_pays((m, s), outcome) else 0.0)
            * x[(m.condition_id, s)]
            for (m, s) in positions
        ) >= 1.0

    prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=5))
    if prob.status != pulp.constants.LpStatusOptimal:
        return None

    allocation = {}
    for (m, s) in positions:
        val = x[(m.condition_id, s)].value() or 0.0
        if val > 1e-6:
            allocation[(m, s)] = val
    return pulp.value(prob.objective), allocation''',
        label="optimizer.py — LP solver"
    ))

    s.append(h3("Greedy fallback"))
    s.append(body(
        "If PuLP is not installed or the LP fails, the "
        "<code>greedy_cover_heuristic()</code> function provides a "
        "set-cover approximation with O(log N) ratio from optimal. It is "
        "useful as a fast pre-filter: if the greedy heuristic finds no "
        "covering portfolio below $1, the LP almost certainly will not "
        "either, so you can skip the LP call entirely on most events."
    ))

    s.append(h2("3.7  Risk module: Kelly sizing and exposure caps"))
    s.append(body(
        "The <code>risk.py</code> module implements the conservative Kelly "
        "sizing formula from Section 1.8, the per-event and per-day "
        "exposure caps, the persistent blacklist, and the slippage "
        "estimator. The risk gate is the final pre-execution checkpoint: "
        "if any constraint is violated, the opportunity is rejected or "
        "downsized."
    ))

    s.append(h3("Conservative Kelly"))
    s.append(body(
        "Full Kelly sizing for a guaranteed-win bet would suggest betting "
        "100% of bankroll, which is clearly wrong in practice because of "
        "settlement risk, leg-failure risk, and execution variance. The "
        "scanner applies two haircuts: a perceived win probability of "
        "0.95 (instead of 1.0) to account for settlement risk, and a "
        "configurable Kelly fraction (default 0.25, i.e., quarter-Kelly) "
        "to dampen variance further. The result is a position size "
        "typically 5-15% of full Kelly, which is the standard conservative "
        "regime for arbitrage strategies."
    ))

    s.extend(code_block(
'''# From risk.py — conservative Kelly sizing
def kelly_fraction(p_win: float, odds_decimal: float) -> float:
    """Full Kelly fraction of bankroll to bet."""
    if p_win <= 0 or p_win >= 1:
        return 0.0
    q = 1 - p_win
    b = odds_decimal - 1
    if b <= 0:
        return 0.0
    f = (p_win * b - q) / b
    return max(0.0, f)

def conservative_kelly_size(
    edge_fraction: float, bankroll: float, cfg: Config,
    perceived_p_win: float = 0.95,
) -> float:
    """Conservative Kelly sizing for an arb opportunity."""
    if edge_fraction <= 0:
        return 0.0
    odds_decimal = 1.0 + edge_fraction
    f_full = kelly_fraction(perceived_p_win, odds_decimal)
    f_adjusted = f_full * cfg.risk.kelly_fraction
    max_bet = bankroll * cfg.risk.kelly_cap_bps / 10_000
    min_bet = bankroll * cfg.risk.kelly_floor_bps / 10_000
    bet = bankroll * f_adjusted
    bet = min(bet, max_bet)
    if bet < min_bet:
        return 0.0
    return bet''',
        label="risk.py — Kelly sizing"
    ))

    s.append(h3("Risk gate"))
    s.append(body(
        "The <code>risk_gate()</code> function runs all pre-execution "
        "checks in order. If any check fails, it returns a "
        "<code>RiskCheckResult</code> with <code>passed=False</code> and "
        "the rejection reason. If a check would be violated by the full "
        "position size but a smaller size would pass, it returns "
        "<code>passed=True</code> with <code>adjusted_size_usdc</code> "
        "set to the maximum allowed size."
    ))

    s.extend(code_block(
'''# From risk.py — risk gate
def risk_gate(opportunity, tracker, blacklist, cfg) -> RiskCheckResult:
    # 1. Blacklist check
    for leg in opportunity.legs:
        if blacklist.contains(leg.market.condition_id):
            return RiskCheckResult(passed=False, reason="blacklisted market")

    # 2. Per-event exposure cap
    event_exp = tracker.event_exposure(opportunity.event_slug)
    if event_exp + opportunity.total_cost > cfg.risk.max_game_exposure_usdc:
        remaining = cfg.risk.max_game_exposure_usdc - event_exp
        if remaining < 100:
            return RiskCheckResult(passed=False, reason="per-event cap reached")
        scale = remaining / opportunity.total_cost
        return RiskCheckResult(passed=True,
            adjusted_size_usdc=opportunity.total_cost * scale,
            reason=f"downsized to fit per-event cap")

    # 3. Daily cap, 4. open positions cap, 5. per-position cap...
    # 6. Slippage check
    sample_leg = opportunity.legs[0]
    if sample_leg.market.book:
        slip_bps = estimate_slippage_bps(
            sample_leg.market.book, opportunity.total_cost, cfg
        )
        if slip_bps > cfg.risk.max_slippage_bps:
            return RiskCheckResult(passed=False, reason="slippage exceeds cap")

    # 7. Kelly sizing
    edge_fraction = opportunity.net_edge / opportunity.total_cost
    kelly_size = conservative_kelly_size(
        edge_fraction=edge_fraction,
        bankroll=cfg.risk.bankroll_usdc,
        cfg=cfg,
    )
    if kelly_size < opportunity.total_cost:
        return RiskCheckResult(passed=True,
            adjusted_size_usdc=kelly_size,
            reason=f"Kelly downsized to ${kelly_size:.0f}")

    return RiskCheckResult(passed=True)''',
        label="risk.py — risk gate"
    ))

    s.append(h2("3.8  Execution engine"))
    s.append(body(
        "The <code>Executor</code> class in <code>executor.py</code> "
        "places all legs of an opportunity, with concurrent placement "
        "when <code>cfg.execution.concurrent_legs</code> is true "
        "(default). Each leg tries maker execution first (limit order at "
        "the desired price), falling back to taker (market order) if the "
        "maker order does not fill within "
        "<code>cfg.execution.maker_timeout_sec</code> seconds."
    ))

    s.append(h3("Concurrent leg placement"))
    s.append(body(
        "Concurrent placement is critical for arbitrage: if you place "
        "legs sequentially, the price can move between legs and you end "
        "up with unhedged exposure. The scanner uses "
        "<code>asyncio.gather</code> to submit all leg orders "
        "simultaneously, then waits for all to complete before assessing "
        "fill results."
    ))

    s.extend(code_block(
'''# From executor.py — concurrent leg placement
async def execute_opportunity(self, opportunity, adjusted_size_usdc=None):
    legs = opportunity.legs
    if adjusted_size_usdc and adjusted_size_usdc < opportunity.total_cost:
        scale = adjusted_size_usdc / opportunity.total_cost
        legs = [Leg(market=l.market, side=l.side, price=l.price,
                    shares=l.shares * scale, cost=l.cost * scale,
                    is_maker=l.is_maker) for l in opportunity.legs]

    if self._dry_run:
        return self._dry_run_position(opportunity, legs), [...]

    # Execute legs concurrently
    if self.cfg.execution.concurrent_legs:
        results = await asyncio.gather(*[self._execute_leg(l) for l in legs])
    else:
        results = [await self._execute_leg(l) for l in legs]

    # Hedge any partial fills
    results = await self._hedge_partials(opportunity, list(results))

    position = self._build_position(opportunity, legs, results)
    return position, results''',
        label="executor.py — concurrent leg placement"
    ))

    s.append(h3("Partial-fill hedging"))
    s.append(body(
        "If some legs fill completely and others fill partially, you are "
        "left with unhedged exposure on the unfilled portion. The "
        "<code>_hedge_partials()</code> method computes the minimum "
        "filled share count across all legs, then sells the excess on "
        "any leg that over-filled. This locks in the matched portion as "
        "a complete arb and leaves you with no unhedged directional risk."
    ))

    s.extend(code_block(
'''# From executor.py — partial-fill hedging
async def _hedge_partials(self, opportunity, results):
    if not self.cfg.execution.hedge_on_partial_fill:
        return results
    has_partial = any(r.is_partial or r.status == OrderStatus.FAILED
                      for r in results)
    if not has_partial:
        return results

    # Min filled across all legs = matched amount
    min_filled = min(
        (r.filled_shares for r in results if r.filled_shares > 0),
        default=0,
    )

    # Sell excess on each over-filled leg
    hedged = []
    for r in results:
        if r.filled_shares > min_filled * 1.01:
            excess = r.filled_shares - min_filled
            token_id = (r.leg.market.token_id_yes
                        if r.leg.side == Side.YES
                        else r.leg.market.token_id_no)
            try:
                await self.order_client.place_market_order(
                    token_id=token_id, side="SELL", size=excess,
                )
                r.filled_shares = min_filled
            except Exception as e:
                log.warning(f"Hedge failed: {e}")
        hedged.append(r)
    return hedged''',
        label="executor.py — partial-fill hedging"
    ))

    s.append(h3("Rollback on critical failure"))
    s.append(body(
        "If execution fails catastrophically (e.g., 2 of 4 legs failed "
        "and the position is now unhedged directional risk), the "
        "<code>rollback_position()</code> function attempts to flatten "
        "the position by selling all filled shares at market. This is "
        "the last line of defense against leg-failure risk."
    ))

    s.append(h2("3.9  Backtesting framework"))
    s.append(body(
        "The <code>backtest.py</code> module provides a framework for "
        "testing the scanner against historical snapshots. It loads "
        "snapshots from JSON files, replays them through the detector "
        "stack, simulates execution with realistic slippage and fees, "
        "and reports performance metrics including total PnL, ROI, win "
        "rate, average edge, max drawdown, and per-strategy-type "
        "breakdowns."
    ))

    s.extend(code_block(
'''# From backtest.py — backtest driver (simplified)
def run_backtest(snapshots, cfg, bankroll_usdc=50_000, sports_filter=None):
    result = BacktestResult()
    result.n_snapshots = len(snapshots)

    for snap in snapshots:
        for event in snap.events:
            if sports_filter and event.sport not in sports_filter:
                continue
            opps = scan_event_for_opportunities(event, cfg)

            for opp in opps:
                result.n_opportunities += 1
                # Simulate execution with slippage
                total_filled_cost = 0.0
                all_filled = True
                for leg in opp.legs:
                    sim = simulate_fill(
                        book=leg.market.book, side="BUY",
                        target_shares=leg.shares, is_maker=leg.is_maker,
                    )
                    if sim.filled_shares < leg.shares * 0.95:
                        all_filled = False; break
                    total_filled_cost += sim.filled_shares * sim.avg_fill_price

                if not all_filled:
                    result.n_failed += 1; continue

                # Compute PnL with fees
                fee = total_filled_cost * (
                    maker_fee_rate() if all(l.is_maker for l in opp.legs)
                    else taker_fee_rate()
                )
                net_cost = total_filled_cost + fee
                payout = opp.guaranteed_payout
                realized = payout - net_cost

                result.realized_pnl_usdc += realized
                result.total_cost_usdc += net_cost
                result.edge_history_bps.append(opp.net_edge_bps)
                # ... track by type, drawdown, etc.

    return result''',
        label="backtest.py — backtest driver"
    ))

    s.append(h2("3.10  Alerts module"))
    s.append(body(
        "The <code>alerts.py</code> module sends notifications to "
        "Telegram and Discord when opportunities are detected, orders "
        "fill, or errors occur. Alerts are filtered by edge threshold "
        "(default: only alert on ≥100 bps edges) to avoid notification "
        "fatigue. The Telegram transport uses the Telegram Bot API; the "
        "Discord transport uses incoming webhooks."
    ))

    s.extend(code_block(
'''# From alerts.py — opportunity alert (Telegram + Discord)
async def send_opportunity_alert(self, opp: Opportunity):
    if opp.net_edge_bps < self.cfg.min_edge_alert_bps:
        return
    msg = (
        f"[ARB] *Arb Opportunity*\\n"
        f"Type: `{opp.type.value}`\\n"
        f"Event: `{opp.event_slug}`\\n"
        f"Net edge: *{opp.net_edge_bps:.0f} bps*\\n"
        f"Cost: ${opp.total_cost:.2f}\\n"
        f"Guaranteed payout: ${opp.guaranteed_payout:.2f}\\n"
        f"Net profit: ${opp.net_edge:.2f}\\n"
        f"Legs: {len(opp.legs)}"
    )
    await self._send_all(msg)

async def _send_telegram(self, text: str):
    if not self.cfg.telegram_bot_token or not self.cfg.telegram_chat_id:
        return
    url = f"https://api.telegram.org/bot{self.cfg.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": self.cfg.telegram_chat_id,
        "text": text, "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        await self.client.post(url, json=payload)
    except Exception as e:
        log.warning(f"Telegram alert error: {e}")''',
        label="alerts.py — opportunity alert"
    ))

    s.append(h2("3.11  Main scanner loop"))
    s.append(body(
        "The <code>Scanner</code> class in <code>scanner.py</code> ties "
        "everything together. The <code>run_forever()</code> method is "
        "the main loop: fetch events, fetch order books, run detectors, "
        "filter through risk gate, execute, alert, sleep, repeat. "
        "Graceful shutdown is handled via SIGINT/SIGTERM signal handlers."
    ))

    s.extend(code_block(
'''# From scanner.py — main loop (simplified)
async def run_forever(self):
    self._running = True
    def _signal_handler(sig, frame):
        self._running = False
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    while self._running:
        try:
            opps = await self.scan_once()
            for opp in opps:
                if not self._running: break
                await self.alerts.send_opportunity_alert(opp)

                # Risk gate
                check = risk_gate(opp, self.tracker, self.blacklist, self.cfg)
                if not check.passed:
                    log.info(f"Skipping opp {opp.id}: {check.reason}")
                    continue

                # Execute
                position, results = await self.executor.execute_opportunity(
                    opp, adjusted_size_usdc=check.adjusted_size_usdc,
                )
                if position.status.value == "FILLED":
                    self.tracker.add(opp)
                await self.alerts.send_fill_alert(position)

            await asyncio.sleep(self.cfg.scanner.poll_interval_sec)
        except Exception as e:
            log.error(f"Scan cycle error: {e}", exc_info=True)
            await self.alerts.send_error_alert(str(e), context="scan_cycle")
            await asyncio.sleep(5.0)
    await self.stop()''',
        label="scanner.py — main loop"
    ))

    s.append(h2("3.12  CLI entry point"))
    s.append(body(
        "The <code>main.py</code> module exposes a CLI with four "
        "subcommands: <code>scan</code> (run live scanner), "
        "<code>backtest</code> (run backtest on saved snapshots), "
        "<code>record</code> (record live snapshots), and "
        "<code>test-api</code> (quick connectivity test). All commands "
        "accept <code>--config</code> for YAML config and "
        "<code>--sports</code> for sport filter."
    ))

    s.extend(code_block(
'''$ python main.py test-api
Testing Polymarket API connectivity...

✓ Gamma API: fetched 10 sports events
    - Lakers vs Celtics (lakers-vs-celtics-jan-15)
    - ...

✓ CLOB API: fetched book for abc123def456
    Question: Will the Lakers defeat the Celtics on January 15?
    Best bid: 0.51
    Best ask: 0.52
    Spread:   0.0100
    Bid depth (5 levels): $4,237.50
    Ask depth (5 levels): $3,891.20

Taker fee: 75 bps (0.75%)
Maker fee: 0 bps (0.00%)''',
        label="main.py test-api output (example)"
    ))

    s.append(h2("3.13  Installation and first run"))
    s.append(body(
        "The companion package ships with a <code>requirements.txt</code> "
        "and a <code>README.md</code>. Installation is standard Python:"
    ))

    s.extend(code_block(
'''$ cd arb_scanner/
$ python -m venv venv && source venv/bin/activate
$ pip install -r requirements.txt

# Test API connectivity (no auth needed)
$ python main.py test-api

# Show current config (defaults + env vars)
$ python main.py show-config

# Run one scan cycle in dry-run mode
$ python main.py scan --once --sports NBA

# Run continuous scanner in dry-run
$ python main.py scan --sports NBA

# Go live (requires API keys)
$ python main.py scan --live --sports NBA''',
        label="Installation and first run"
    ))

    s.append(body(
        "Before going live, set the required environment variables: "
        "<code>POLY_API_KEY</code>, <code>POLY_API_SECRET</code>, "
        "<code>POLY_API_PASSPHRASE</code>, <code>POLY_PRIVATE_KEY</code>, "
        "and <code>POLY_WALLET_ADDRESS</code>. Optional variables include "
        "<code>POLY_TG_TOKEN</code> and <code>POLY_TG_CHAT_ID</code> for "
        "Telegram alerts, <code>POLY_DISCORD_WEBHOOK</code> for Discord, "
        "and <code>POLY_BANKROLL_USDC</code> to override the default "
        "bankroll. Never commit real keys to version control."
    ))

    s.append(chapter_break())
    return s
