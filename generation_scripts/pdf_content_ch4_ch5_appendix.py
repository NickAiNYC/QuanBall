"""
pdf_content_ch4_ch5_appendix.py — Chapter 4 (Production Hardening),
Chapter 5 (Edge Maintenance), Appendix A (Code Index), Appendix B (Math Reference).
"""
from pdf_helpers import (
    h1, h2, h3, h4, body, bullet, numbered, kicker, math_block,
    callout, warning, info, key_insight, code_block, std_table, caption,
    hr, soft_break, chapter_break, ACCENT_EMERALD, ACCENT_AMBER,
)
from reportlab.platypus import Paragraph, Spacer


# ─────────────────────────────────────────────────────────────────────────────
# CHAPTER 4 — Production Hardening
# ─────────────────────────────────────────────────────────────────────────────

def chapter_4():
    s = []
    s.append(kicker("Chapter 4 · Production Hardening"))
    s.append(h1("Production Hardening"))
    s.append(body(
        "A scanner that works in dry-run is not a scanner that prints money. "
        "This chapter covers the operational engineering required to take "
        "the implementation from Chapter 3 and run it profitably in "
        "production: low-latency infrastructure, slippage and fee modeling, "
        "in-play execution, monitoring, scaling architecture, and "
        "compliance. Every recommendation here comes from production "
        "incidents — either experienced directly or observed in the broader "
        "Polymarket operator community."
    ))

    s.append(h2("4.1  Low-latency infrastructure"))
    s.append(body(
        "Latency in the scanner pipeline has three components: data "
        "ingestion (fetching events and books), detection (running the "
        "detectors on the resolved data), and execution (placing orders). "
        "For pre-game sports arbitrage, total latency budgets of 1-2 "
        "seconds are acceptable because edges persist for tens of seconds. "
        "For in-play arbitrage, the budget collapses to 200-500 milliseconds "
        "— the edge window after a scoring play is often under 5 seconds, "
        "and competing bots will close the gap within 2 seconds."
    ))

    s.append(h3("VPS region selection"))
    s.append(body(
        "Polymarket's CLOB API is hosted on AWS us-east-1. The Polygon RPC "
        "endpoints are geographically distributed, but the canonical "
        "polygon-rpc.com endpoint is also us-east-1. Running the scanner "
        "from a us-east-1 VPS gives single-digit-millisecond API latency. "
        "Running from Europe or Asia adds 80-200ms of network round-trip, "
        "which is acceptable for pre-game but marginal for in-play. For "
        "serious in-play operation, a us-east-1 VPS (or co-located bare "
        "metal) is essentially mandatory."
    ))

    rows = [
        ["AWS us-east-1 (Virginia)", "1-5 ms", "$5-50/mo", "Best for in-play; co-located with Polymarket infra"],
        ["AWS us-west-2 (Oregon)", "60-80 ms", "$5-50/mo", "Acceptable for pre-game only"],
        ["GCP us-central1 (Iowa)", "20-40 ms", "$5-50/mo", "Good compromise"],
        ["EU (Frankfurt)", "80-100 ms", "€5-50/mo", "Marginal even for pre-game"],
        ["Asia (Singapore)", "200-250 ms", "$5-50/mo", "Not recommended"],
    ]
    s.append(std_table(
        ["VPS region", "Latency to CLOB", "Cost", "Notes"],
        rows,
        col_ratios=[0.30, 0.18, 0.14, 0.38],
    ))
    s.append(caption("Table 4.1 — VPS region latency to Polymarket CLOB API"))

    s.append(h3("WebSocket reconnection"))
    s.append(body(
        "WebSocket disconnects are inevitable. The <code>CLOBWSClient</code> "
        "in <code>clob_client.py</code> handles reconnection with "
        "exponential backoff (1s, 2s, 5s, 10s, 30s, 60s), but you should "
        "also implement a heartbeat monitor that alerts if the WebSocket "
        "has been disconnected for more than 60 seconds. A silent "
        "disconnection is the most common cause of stale-data trades: the "
        "scanner thinks it has fresh books but is actually trading against "
        "a snapshot from minutes ago."
    ))
    s.append(body(
        "For high-availability deployment, run two scanner instances in "
        "different us-east-1 availability zones (us-east-1a and "
        "us-east-1b). The primary instance executes trades; the secondary "
        "watches the same data stream and alerts if it detects an "
        "opportunity the primary missed. This catches both "
        "instance-level failures and order-placement bugs."
    ))

    s.append(h3("Rate limit handling"))
    s.append(body(
        "Polymarket's CLOB API has a soft rate limit of approximately 10 "
        "requests per second per IP. The scanner respects this via "
        "<code>httpx.Limits</code> (max connections) and a "
        "<code>asyncio.Semaphore</code> in "
        "<code>get_books_for_markets()</code> (max concurrent book "
        "fetches). If you exceed the limit, the API returns HTTP 429 "
        "with a <code>Retry-After</code> header. The scanner's retry "
        "logic in <code>_get()</code> handles this automatically."
    ))
    s.append(body(
        "For higher throughput, shard by event slug across multiple VPS "
        "instances, each with its own IP. A two-instance shard can "
        "double effective throughput; a four-instance shard can quadruple "
        "it. Coordinate via a shared Redis instance to avoid duplicate "
        "executions of the same opportunity."
    ))

    s.append(h2("4.2  Slippage and fee modeling"))
    s.append(body(
        "Theoretical edge is what the detector reports; realized edge is "
        "what hits your bankroll after slippage and fees. The gap between "
        "the two is the single biggest source of disappointment for new "
        "arbitrage operators. This section covers the slippage and fee "
        "model used by the scanner's risk gate."
    ))

    s.append(h3("Depth-weighted slippage"))
    s.append(body(
        "The <code>estimate_slippage_bps()</code> function walks the "
        "order book to compute the volume-weighted average price (VWAP) "
        "for a target notional, then compares it to the best ask. For "
        "small orders in liquid books, slippage is near zero. For large "
        "orders in thin books, slippage can easily exceed the arbitrage "
        "edge itself. The risk gate rejects opportunities where estimated "
        "slippage exceeds <code>cfg.risk.max_slippage_bps</code> (default "
        "50 bps)."
    ))
    s.append(body(
        "A common mistake is to model slippage linearly — for example, 5 "
        "bps per $1,000 of notional. In reality, slippage is non-linear: "
        "it stays near zero until your order starts consuming levels "
        "beyond the top of book, then rises sharply. The scanner's "
        "book-walking simulator captures this non-linearity accurately. "
        "Always trust the simulator over a linear approximation."
    ))

    s.append(h3("Fee-aware threshold adjustment"))
    s.append(body(
        "The min-edge thresholds in <code>ScannerConfig</code> are split "
        "by execution mode: <code>min_edge_taker_bps = 75</code> (must "
        "clear the 0.75% taker fee exactly) and "
        "<code>min_edge_maker_bps = 30</code> (just slippage buffer, "
        "since maker fee is zero). For 50/50 markets where the taker fee "
        "bites hardest, consider raising the taker threshold to 100 bps "
        "to leave a profit margin after slippage. For deep markets with "
        "tight spreads, the maker threshold can drop to 15-20 bps."
    ))

    rows = [
        ["Deep (>$10k each side)", "0.97", "0.9926", "15-25 bps", "75-100 bps"],
        ["Medium ($1k-$10k)", "0.95", "0.9926", "25-40 bps", "100-150 bps"],
        ["Thin (<$1k)", "0.90", "0.9926", "50+ bps", "Skip (slippage too high)"],
        ["In-play (live game)", "0.85", "0.9926", "30-50 bps", "150+ bps"],
    ]
    s.append(std_table(
        ["Liquidity regime", "Fill probability", "Break-even sum", "Maker threshold", "Taker threshold"],
        rows,
        col_ratios=[0.24, 0.15, 0.16, 0.22, 0.23],
    ))
    s.append(caption("Table 4.2 — Recommended edge thresholds by liquidity regime"))

    s.append(h2("4.3  In-play / live opportunities"))
    s.append(body(
        "In-play arbitrage — trading during live games — is where the "
        "highest edges live, but it is also the most operationally "
        "demanding. The edge windows open and close in seconds, and "
        "competing bots are watching the same data feed. The good news: "
        "sports retail flow is at its most emotional during live games, "
        "which means prices are at their most inefficient."
    ))

    s.append(h3("When in-play edges appear"))
    s.append(body(
        "The three highest-edge windows during a live game are: "
        "(1) immediately after a scoring play, when the order book lags "
        "the new game state by 1-3 seconds; (2) after an injury "
        "announcement, when the market re-prices over 5-15 seconds; "
        "(3) during momentum shifts (e.g., a 10-0 run in basketball), "
        "when emotional betting creates transient mispricings. Each "
        "window has a different edge profile and requires a different "
        "execution strategy."
    ))

    s.append(h3("Faster execution path for in-play"))
    s.append(body(
        "The standard scanner loop (5-second poll interval, full event "
        "refresh) is too slow for in-play. The in-play execution path "
        "subscribes to the CLOB WebSocket for the specific token IDs of "
        "in-progress games, runs the single-market detector on every "
        "book delta, and executes via market orders (taker) rather than "
        "limit orders (maker). The maker path is too slow for in-play "
        "because limit orders may not fill before the edge closes."
    ))
    s.append(body(
        "The trade-off: in-play execution pays the 0.75% taker fee on "
        "both legs, so the gross edge must exceed 150 bps to be "
        "profitable. This is a much higher bar than pre-game maker "
        "execution, but the in-play edge windows are also much larger "
        "— a 500-1000 bps edge during a momentum shift is not uncommon."
    ))

    s.extend(warning(
        "In-play execution is the highest-risk mode. Books move fast, "
        "partial fills are common, and a single missed leg can leave you "
        "with significant unhedged directional exposure. Run in-play "
        "with reduced position sizes (50% of pre-game Kelly) and a "
        "tighter slippage cap (25 bps max). Never run in-play unattended "
        "until you have logged at least 100 hours of dry-run observation."
    ))

    s.append(h2("4.4  Monitoring dashboard"))
    s.append(body(
        "A scanner without monitoring is a scanner that will quietly "
        "bleed money when something goes wrong. The minimum viable "
        "monitoring stack tracks PnL, edge history, fill rates, and "
        "slippage distribution. For production, add leader-board "
        "correlation (tracking the wallets of known profitable operators) "
        "and per-strategy Sharpe ratios."
    ))

    s.append(h3("Key metrics to track"))
    s.append(bullet(
        "<b>Realized PnL</b> — running total, daily, weekly, monthly. "
        "Plot as time series; alert on drawdown exceeding 2× expected "
        "daily volatility."
    ))
    s.append(bullet(
        "<b>Edge history</b> — histogram of detected edge bps. Should be "
        "roughly log-normal with a long right tail. If the distribution "
        "shifts left, the market is becoming more efficient and your "
        "thresholds need adjustment."
    ))
    s.append(bullet(
        "<b>Fill rate</b> — fraction of attempted legs that filled "
        "completely. Pre-game maker execution typically fills 60-80%; "
        "in-play taker execution should fill 90%+. Drops below 50% "
        "indicate a stale book or a broken order-placement path."
    ))
    s.append(bullet(
        "<b>Slippage distribution</b> — actual slippage in bps, "
        "comparing avg fill price to detector-reported price. If actual "
        "slippage consistently exceeds estimated slippage, the "
        "slippage model needs recalibration."
    ))
    s.append(bullet(
        "<b>Per-strategy Sharpe</b> — rolling 30-day Sharpe ratio by "
        "strategy type. Kill switches on any strategy whose Sharpe "
        "drops below 1.0 (annualized)."
    ))
    s.append(bullet(
        "<b>Leaderboard correlation</b> — track the top 10 Polymarket "
        "wallets by PnL. If your fills start correlating with theirs, "
        "you are competing for the same edges; if your fills diverge "
        "from theirs, either you found a new edge or you are missing "
        "the existing one."
    ))

    s.append(h3("Dashboard implementation"))
    s.append(body(
        "For a lightweight dashboard, use Streamlit or Grafana backed by "
        "a TimescaleDB or ClickHouse instance. The scanner writes a row "
        "to the database for every opportunity detected and every "
        "position closed, with columns for timestamp, strategy type, "
        "edge, cost, payout, realized PnL, slippage, and fill rate. "
        "Dashboards query this table directly with time-window "
        "aggregations."
    ))

    s.append(h2("4.5  Scaling architecture"))
    s.append(body(
        "A single scanner instance can comfortably monitor 50-100 sports "
        "events with 5-10 markets each — that is 250-1000 markets, well "
        "within the API rate limits. To scale to thousands of markets "
        "per day (the full Polymarket sports calendar across NBA, NFL, "
        "MLB, NHL, soccer, tennis, MMA), you need a sharded architecture."
    ))

    s.append(h3("Sharding by sport/league"))
    s.append(body(
        "The simplest sharding strategy is by sport: one scanner instance "
        "per sport (NBA scanner, NFL scanner, soccer scanner, etc.). Each "
        "instance has its own API rate limit budget, its own VPS, and its "
        "own bankroll allocation. Coordination is minimal — the only "
        "shared state is the blacklist and the exposure tracker, both of "
        "which can be backed by Redis."
    ))

    s.append(h3("Async I/O vs Celery"))
    s.append(body(
        "The scanner's main loop is async-first (<code>asyncio</code>), "
        "which is optimal for I/O-bound work (HTTP requests, WebSocket "
        "messages). For CPU-bound work — specifically the LP solver in "
        "<code>optimizer.py</code> — offload to a Celery worker pool "
        "backed by Redis or RabbitMQ. The scanner's detector publishes "
        "LP-solve tasks to a Celery queue; the worker pool solves them "
        "in parallel and returns the optimal allocation. This keeps the "
        "event loop responsive while still solving LPs in parallel across "
        "CPU cores."
    ))

    s.append(h3("Hot/cold market tiering"))
    s.append(body(
        "Not all markets deserve the same scan frequency. Tier markets "
        "by activity: hot markets (in-play, or about to resolve within "
        "1 hour) get WebSocket subscriptions with sub-second updates; "
        "warm markets (resolving within 12 hours) get 5-second polling; "
        "cold markets (resolving in 1-7 days) get 60-second polling. "
        "This tiering reduces API load by 80%+ compared to uniform "
        "high-frequency polling of all markets."
    ))

    rows = [
        ["Hot", "In-play or resolves <1h", "WebSocket", "Sub-second", "Maker + taker"],
        ["Warm", "Resolves 1-12h", "REST poll", "5 seconds", "Maker preferred"],
        ["Cold", "Resolves 1-7 days", "REST poll", "60 seconds", "Maker only"],
        ["Stale", "No trades in 1h+", "Skip", "—", "—"],
    ]
    s.append(std_table(
        ["Tier", "Definition", "Transport", "Frequency", "Execution"],
        rows,
        col_ratios=[0.10, 0.28, 0.20, 0.20, 0.22],
    ))
    s.append(caption("Table 4.3 — Market tiering for scan frequency"))

    s.append(h2("4.6  Legal and compliance"))
    s.append(body(
        "Polymarket operates in a regulatory gray area. The platform is "
        "technically available only to non-US users, but US users can "
        "access it via VPN. Whether this is legal in your jurisdiction "
        "is a question for a lawyer, not this guide. The compliance "
        "notes below are operational best practices, not legal advice."
    ))

    s.append(h3("USDC custody on Polygon"))
    s.append(body(
        "All trading capital lives as USDC on the Polygon blockchain. "
        "Wallet security is therefore paramount. Recommended setup: a "
        "hardware wallet (Ledger or Trezor) holds the treasury; a "
        "hot wallet with limited funds (1-5% of treasury) handles "
        "active trading. Refill the hot wallet from the hardware wallet "
        "weekly. Never store the private key in plain text on the VPS — "
        "use environment variables loaded from an encrypted secrets "
        "manager (AWS Secrets Manager, HashiCorp Vault, or age-encrypted "
        "files at rest)."
    ))

    s.append(h3("Tax lot tracking"))
    s.append(body(
        "Every fill is a taxable event in most jurisdictions. The US "
        "treats prediction market gains as short-term capital gains "
        "(ordinary income rate) regardless of holding period, because "
        "the contracts are considered Section 1256 contracts in some "
        "interpretations and gambling winnings in others. The exact "
        "treatment is genuinely uncertain — consult a tax professional. "
        "The scanner should log every fill with timestamp, price, "
        "shares, and fee, and export to CSV for accountant review at "
        "year-end."
    ))

    s.append(h3("Wallet security best practices"))
    s.append(bullet(
        "Never expose <code>POLY_PRIVATE_KEY</code> in code, logs, or "
        "shell history. Use environment variables loaded from an "
        "encrypted source."
    ))
    s.append(bullet(
        "Use a dedicated trading wallet, separate from your main "
        "Ethereum wallet. If the trading wallet is compromised, only "
        "the trading capital is at risk."
    ))
    s.append(bullet(
        "Set up transaction alerts on the trading wallet — every "
        "outgoing transaction triggers a Telegram notification. If you "
        "see a transaction you did not authorize, you can react within "
        "seconds."
    ))
    s.append(bullet(
        "Use a multi-sig wallet (Gnosis Safe) for the treasury. "
        "Require 2-of-3 signatures for any withdrawal over $10,000. "
        "This prevents a single compromised key from draining the "
        "treasury."
    ))

    s.append(chapter_break())
    return s


# ─────────────────────────────────────────────────────────────────────────────
# CHAPTER 5 — Edge Maintenance & Failure Modes
# ─────────────────────────────────────────────────────────────────────────────

def chapter_5():
    s = []
    s.append(kicker("Chapter 5 · Strategy & Maintenance"))
    s.append(h1("Edge Maintenance & Failure Modes"))
    s.append(body(
        "Arbitrage edges decay. As more operators build scanners and "
        "compete for the same opportunities, the gross edge per trade "
        "shrinks. This chapter covers why sports has stayed inefficient "
        "longer than politics, the common failure modes that take down "
        "amateur scanners, hybrid strategies that combine Polymarket "
        "arbitrage with other edges, and a roadmap for evolving the "
        "scanner as the market matures."
    ))

    s.append(h2("5.1  Why sports stays inefficient"))
    s.append(body(
        "The article framing this guide makes the case clearly: sports "
        "stays inefficient because of who trades it. Politics arbitrage "
        "gets picked over by smart money — quants, funds, and bot squads "
        "all camp the election. Sports gets retail. People bet their "
        "team with their heart. They pile into a YES on emotion the "
        "second their guy scores. Then an injury hits, a ref call "
        "lands, momentum flips, and the price lags the new reality for "
        "a few seconds while the order book catches up."
    ))
    s.append(body(
        "This compositional difference is structural, not transient. "
        "The smart money that does trade sports tends to focus on "
        "high-stakes events (Super Bowl, NBA Finals) where liquidity "
        "supports large positions. The nightly NBA, NFL, and MLB "
        "regular-season games are left to retail flow and a handful of "
        "small-to-mid arbitrage operators. As long as retail flow "
        "dominates these markets, the inefficiency will persist."
    ))

    s.append(h3("Sources of sports inefficiency"))
    s.append(body(
        "Beyond retail emotion, several structural factors keep sports "
        "markets inefficient:"
    ))
    s.append(bullet(
        "<b>Recency bias on injuries</b> — when a star player is "
        "announced as injured 30 minutes before tipoff, the sportsbooks "
        "re-price within seconds but Polymarket often lags by 30-60 "
        "seconds because the order book is thinner."
    ))
    s.append(bullet(
        "<b>Lag between sportsbook line moves and Polymarket "
        "re-pricing</b> — Pinnacle and Circa move their NBA lines "
        "constantly based on sharp action; Polymarket prices follow "
        "with a 5-30 second delay. This is the cleanest cross-platform "
        "edge."
    ))
    s.append(bullet(
        "<b>Emotional betting on popular teams</b> — Lakers, Cowboys, "
        "Yankees games see disproportionate YES volume on the popular "
        "team regardless of true odds. The overvalued side is "
        "consistently the popular team."
    ))
    s.append(bullet(
        "<b>In-play momentum shifts</b> — a 10-0 run in basketball "
        "creates an emotional cascade of bets on the leading team, "
        "driving the price 5-10 cents above fair value for 30-60 "
        "seconds."
    ))

    s.append(h2("5.2  Common failure modes"))
    s.append(body(
        "Most amateur arbitrage scanners fail in predictable ways. The "
        "failure modes below are ordered by frequency observed in the "
        "wild."
    ))

    s.append(h3("Failure 1: Leg execution failure"))
    s.append(body(
        "<b>Symptom:</b> One leg of a multi-leg arb fills, the other "
        "does not, leaving unhedged directional exposure. "
        "<b>Cause:</b> Order book moves between leg submission and fill, "
        "or one leg has insufficient depth. <b>Mitigation:</b> "
        "Concurrent leg placement (Section 3.8), partial-fill hedging "
        "(Section 3.8), and rollback on critical failure. Pre-trade "
        "depth check should require both sides to have at least 2× the "
        "target notional in the top 5 levels."
    ))

    s.append(h3("Failure 2: Resolution disputes"))
    s.append(body(
        "<b>Symptom:</b> A market you bet on enters UMA dispute and "
        "resolves against you, turning a guaranteed win into a loss. "
        "<b>Cause:</b> Ambiguous resolution criteria — rain-delayed MLB "
        "games, NFL overtime edge cases, markets where the question "
        "text is imprecise. <b>Mitigation:</b> Blacklist markets with "
        "prior disputes; avoid markets with ambiguous resolution "
        "language; size positions with a 5-10% settlement-risk haircut."
    ))

    s.append(h3("Failure 3: Liquidity mirage"))
    s.append(body(
        "<b>Symptom:</b> The detector reports a deep book, but your "
        "order only fills 20% before the book vanishes. <b>Cause:</b> "
        "The top-of-book was a single large order that got pulled the "
        "moment you started filling against it — either a market maker "
        "responding to your order, or a spoofing order that was never "
        "intended to fill. <b>Mitigation:</b> Use the depth-weighted "
        "slippage estimator (Section 2.5), not just top-of-book. Reject "
        "opportunities where the top 5 levels do not have at least 2× "
        "your target notional."
    ))

    s.append(h3("Failure 4: Fee threshold miscalibration"))
    s.append(body(
        "<b>Symptom:</b> The scanner reports profitable trades but the "
        "bankroll declines over time. <b>Cause:</b> The min-edge "
        "threshold is set below the actual all-in cost (fee + slippage + "
        "settlement risk), so the scanner is taking trades with "
        "negative expected value. <b>Mitigation:</b> Track realized PnL "
        "per trade against detected edge; if realized < detected by more "
        "than 30 bps consistently, raise the threshold."
    ))

    s.append(h3("Failure 5: NegRisk settlement bugs"))
    s.append(body(
        "<b>Symptom:</b> A NegRisk multi-outcome market settles in an "
        "unexpected way, leaving your covering portfolio with a hole. "
        "<b>Cause:</b> NegRisk resolution logic is more complex than "
        "binary markets; edge cases around tie-breaking, withdrawal, "
        "and dispute resolution can produce surprising outcomes. "
        "<b>Mitigation:</b> Treat NegRisk arbitrage as Category 3 "
        "(edge-adjusted, not riskless) and size with full Kelly haircut. "
        "Avoid NegRisk markets with more than 12 outcomes — settlement "
        "complexity scales super-linearly."
    ))

    s.append(h3("Failure 6: Hot wallet drainers"))
    s.append(body(
        "<b>Symptom:</b> The trading wallet is drained to zero with no "
        "fills in the scanner log. <b>Cause:</b> The private key was "
        "compromised — typically via a phishing attack on the operator, "
        "a leaked environment variable, or a malicious dependency in "
        "<code>pip install</code>. <b>Mitigation:</b> Hardware wallet "
        "for treasury, hot wallet with limited funds, transaction "
        "alerts, multi-sig for large withdrawals. Audit "
        "<code>requirements.txt</code> dependencies regularly with "
        "<code>pip-audit</code>."
    ))

    s.append(h3("Failure 7: API rate limit cascades"))
    s.append(body(
        "<b>Symptom:</b> The scanner enters a retry loop, hits rate "
        "limits on retries, and effectively shuts down for minutes at a "
        "time. <b>Cause:</b> A transient API error triggers retries, "
        "which themselves trigger more retries, which exhaust the rate "
        "limit. <b>Mitigation:</b> Exponential backoff with jitter, "
        "circuit breaker that pauses scanning for 60 seconds after 5 "
        "consecutive failures, and rate limit budget tracking that "
        "throttles new requests before hitting the limit."
    ))

    s.append(h2("5.3  Hybrid strategies"))
    s.append(body(
        "Pure Polymarket arbitrage is one edge among many. The most "
        "profitable operators combine it with related strategies that "
        "share infrastructure but harvest different inefficiencies. "
        "Below are three hybrid strategies worth considering once the "
        "core scanner is stable."
    ))

    s.append(h3("Polymarket arb + sportsbook promo arb"))
    s.append(body(
        "Traditional sportsbooks offer deposit bonuses, free bets, and "
        "odds boosts as acquisition tools. These promotions often have "
        "positive expected value on their own, but combining them with "
        "Polymarket arbitrage creates a higher-confidence edge. For "
        "example: a sportsbook offers a $500 free bet on the Lakers "
        "moneyline at +150 (post-promo); Polymarket has Lakers YES at "
        "$0.55. Take the free bet on the sportsbook (expected value "
        "≈ $300), and hedge by buying Celtics YES on Polymarket for "
        "$275. Either outcome: Lakers win → sportsbook pays $750, "
        "Polymarket loses $275, net $475; Celtics win → sportsbook "
        "loses nothing (free bet), Polymarket pays $500, net $225. "
        "Expected value ≈ $350, risk-free."
    ))

    s.append(h3("Parlay insurance farming"))
    s.append(body(
        "Many sportsbooks offer parlay insurance — if one leg of a "
        "5-leg parlay loses, the stake is refunded as a free bet. The "
        "strategy: construct a 5-leg parlay where 4 legs are "
        "high-probability and the 5th is a low-probability longshot "
        "that you actively want to lose. If the longshot loses (high "
        "probability), you get the stake back as a free bet to deploy "
        "on Polymarket arbitrage. If the longshot wins, you collect "
        "the parlay payout (which is large). Either outcome is "
        "positive expected value, and the capital cycles back into "
        "your Polymarket scanner."
    ))

    s.append(h3("Free-bet conversion"))
    s.append(body(
        "Free bets on sportsbooks typically pay only the winnings, not "
        "the stake. The optimal strategy is to deploy free bets on "
        "longshot markets (high decimal odds) to maximize expected "
        "value. Polymarket arbitrage complements this by providing a "
        "place to deploy the converted free-bet winnings at "
        "risk-free rates while waiting for the next sportsbook "
        "promotion."
    ))

    s.append(h2("5.4  Edge decay monitoring"))
    s.append(body(
        "Every arbitrage edge decays over time as more operators "
        "compete for it. The scanner should track per-strategy "
        "performance over rolling 30-day windows and alert when a "
        "strategy's Sharpe ratio drops below a kill threshold. "
        "Recommended thresholds:"
    ))

    rows = [
        ["Single-market (maker)", "1.5", "1.0", "Raise min_edge_maker_bps by 5 bps"],
        ["Single-market (taker)", "1.0", "0.5", "Switch fully to maker; consider pausing taker"],
        ["NegRisk rebalance", "0.8", "0.3", "Pause; only run during event windows"],
        ["Combinatorial (LP)", "1.2", "0.7", "Recheck feasibility constraints; tighten LP"],
        ["Cross-platform", "1.0", "0.5", "Recalibrate sportsbook vig assumption"],
    ]
    s.append(std_table(
        ["Strategy", "Healthy Sharpe", "Kill threshold", "Action on kill"],
        rows,
        col_ratios=[0.28, 0.18, 0.18, 0.36],
    ))
    s.append(caption("Table 5.1 — Edge decay monitoring thresholds (rolling 30-day Sharpe)"))

    s.append(body(
        "When a strategy hits its kill threshold, do not delete it — "
        "just disable it temporarily and recheck weekly. Edges sometimes "
        "recover when competitor bots get redeployed elsewhere or when "
        "market structure shifts. A strategy that was killed in March "
        "might be profitable again in October."
    ))

    s.append(h2("5.5  Roadmap"))
    s.append(body(
        "The scanner described in this guide is a starting point. Three "
        "directions worth exploring once the core system is stable:"
    ))

    s.append(h3("ML-based dependency discovery"))
    s.append(body(
        "The current combinatorial detector uses hand-written regex "
        "patterns to classify markets by category (moneyline, spread, "
        "total, player prop) and hand-coded feasibility constraints to "
        "prune impossible atomic outcomes. A production system should "
        "replace this with a fine-tuned language model that reads "
        "market questions and outputs structured (category, team_home, "
        "team_away, spread_value, total_value) tuples. This unlocks "
        "combinatorial arbitrage on novel market types that the regex "
        "patterns miss."
    ))

    s.append(h3("Market-making hybrid"))
    s.append(body(
        "Pure arbitrage captures the spread when it inverts, but most "
        "of the time the spread is positive and you are flat. A "
        "market-making layer can capture the spread continuously by "
        "resting limit orders on both sides of normal (non-inverted) "
        "markets, earning the maker fee (zero) and capturing the spread "
        "when both sides fill. This is a different risk profile — you "
        "carry inventory risk — but it dramatically increases capital "
        "efficiency. The infrastructure (order book monitoring, "
        "limit-order placement, position tracking) is identical to the "
        "arbitrage scanner."
    ))

    s.append(h3("Cross-venue HFT"))
    s.append(body(
        "The cross-platform detector in this guide is a low-frequency "
        "tool — it compares Polymarket prices to sportsbook odds every "
        "30-60 seconds. A production cross-venue system would subscribe "
        "to a sportsbook odds feed (Pinnacle's API, for example) and "
        "the Polymarket WebSocket simultaneously, executing within "
        "milliseconds of a line move. This requires significant "
        "infrastructure (co-located servers, sportsbook API access, "
        "capital on both venues) but captures the cleanest edge in the "
        "strategy space."
    ))

    s.append(h2("5.6  Closing thoughts"))
    s.append(body(
        "The edge in Polymarket sports arbitrage is real, repeatable, "
        "and accessible to operators with moderate engineering resources. "
        "The 2026 fee change made the game harder, but the maker-fee "
        "loophole preserves the edge for operators willing to do the "
        "operational work of resting limit orders and managing fill "
        "risk. The nightly cadence of professional sports produces a "
        "fresh batch of opportunities every day, unlike the seasonal "
        "cadence of politics that leaves capital idle for months at a "
        "time."
    ))
    s.append(body(
        "The wallets quietly printing month after month on Polymarket "
        "are pointed at the games, not the elections. Point your "
        "scanner where the games are."
    ))

    s.append(chapter_break())
    return s


# ─────────────────────────────────────────────────────────────────────────────
# APPENDIX A — Code Module Index
# ─────────────────────────────────────────────────────────────────────────────

def appendix_a():
    s = []
    s.append(kicker("Appendix A · Code Package"))
    s.append(h1("Code Module Index"))
    s.append(body(
        "The companion Python package contains twelve runnable modules "
        "totaling roughly 2,500 lines of code. This appendix lists each "
        "module, its purpose, key public functions, and dependencies. "
        "All modules live in the <code>arb_scanner/</code> directory of "
        "the deliverable."
    ))

    rows = [
        ["config.py", "Configuration dataclasses + env/YAML loaders + fee constants", "load_config(), taker_fee_rate(), maker_fee_rate()", "PyYAML"],
        ["models.py", "Domain dataclasses: Market, OrderBook, Opportunity, Position, etc.", "Market, OrderBook, Opportunity, Leg, Position, AtomicOutcome", "—"],
        ["gamma_client.py", "Polymarket Gamma API client (events, markets, metadata)", "GammaClient, detect_sport(), detect_category()", "httpx"],
        ["clob_client.py", "CLOB REST + WS clients (order books, prices, order placement)", "CLOBRestClient, CLOBWSClient, CLOBOrderClient", "httpx, websockets, py-clob-client"],
        ["detectors.py", "Opportunity detectors: 4 strategy types", "detect_single_market_arb(), detect_negrisk_rebalance_arb(), detect_combinatorial_arb(), detect_cross_platform_arb()", "models, config"],
        ["optimizer.py", "PuLP LP solver for combinatorial covering portfolios", "solve_covering_lp(), greedy_cover_heuristic(), is_feasible_outcome()", "pulp"],
        ["risk.py", "Kelly sizing, exposure tracker, blacklist, slippage estimator", "conservative_kelly_size(), risk_gate(), ExposureTracker, Blacklist", "models, config"],
        ["executor.py", "Concurrent leg execution, partial-fill hedging, rollback", "Executor, LegExecutionResult, rollback_position()", "clob_client, models"],
        ["alerts.py", "Telegram + Discord notifications", "AlertSender (send_opportunity_alert, send_fill_alert, send_error_alert)", "httpx"],
        ["scanner.py", "Main scanner loop tying everything together", "Scanner, setup_logging()", "all other modules"],
        ["backtest.py", "Historical backtest framework + snapshot recorder", "run_backtest(), load_snapshots(), record_snapshots()", "detectors, models"],
        ["main.py", "CLI entry point (scan, backtest, record, test-api, show-config)", "main()", "scanner, backtest, config"],
    ]
    s.append(std_table(
        ["Module", "Purpose", "Key public API", "Dependencies"],
        rows,
        col_ratios=[0.14, 0.28, 0.34, 0.24],
    ))
    s.append(caption("Table A.1 — Code module index"))

    s.append(h2("A.1  Installation"))
    s.extend(code_block(
'''$ cd arb_scanner/
$ python -m venv venv && source venv/bin/activate
$ pip install -r requirements.txt

# Verify installation
$ python main.py show-config

# Test API connectivity (no auth needed)
$ python main.py test-api''',
        label="Installation"
    ))

    s.append(h2("A.2  Environment variables"))
    s.extend(code_block(
'''# Required for live trading
export POLY_API_KEY="..."
export POLY_API_SECRET="..."
export POLY_API_PASSPHRASE="..."
export POLY_PRIVATE_KEY="0x..."
export POLY_WALLET_ADDRESS="0x..."

# Optional: faster Polygon RPC
export POLY_RPC_URL="https://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY"

# Optional: alerts
export POLY_TG_TOKEN="..."
export POLY_TG_CHAT_ID="..."
export POLY_DISCORD_WEBHOOK="https://discord.com/api/webhooks/..."

# Optional: override defaults
export POLY_BANKROLL_USDC=50000
export POLY_MIN_EDGE_TAKER_BPS=75

# Optional: YAML config file
export POLY_CONFIG_PATH="./config.yaml"''',
        label="Environment variables"
    ))

    s.append(h2("A.3  requirements.txt"))
    s.extend(code_block(
'''# Polymarket Sports Arbitrage Scanner — Dependencies
# Tested with Python 3.11+

# Core async HTTP / WS
httpx>=0.27.0
websockets>=12.0

# Configuration
PyYAML>=6.0

# Polymarket official SDK (order placement, signing)
py-clob-client>=0.20.0

# Linear programming (combinatorial arbitrage)
pulp>=2.7.0''',
        label="requirements.txt"
    ))

    s.append(chapter_break())
    return s


# ─────────────────────────────────────────────────────────────────────────────
# APPENDIX B — Mathematical Reference
# ─────────────────────────────────────────────────────────────────────────────

def appendix_b():
    s = []
    s.append(kicker("Appendix B · Reference"))
    s.append(h1("Mathematical Reference"))
    s.append(body(
        "Condensed formula sheet for quick reference. Each formula below "
        "is used in the production scanner; the section references point "
        "back to the full derivation in Chapter 1."
    ))

    s.append(h2("B.1  Implied probability & overround"))
    s.append(body("Given YES ask P_yes and NO ask P_no:"))
    s.append(math_block("p_implied(YES) = P_yes"))
    s.append(math_block("p_implied(NO)  = P_no"))
    s.append(math_block("overround = (P_yes + P_no) − $1"))
    s.append(math_block("p_norm(YES) = P_yes / (P_yes + P_no)"))
    s.append(math_block("p_norm(NO)  = P_no  / (P_yes + P_no)"))

    s.append(h2("B.2  Single-market arbitrage"))
    s.append(body("Buy 1 YES at ask + 1 NO at (1 − YES bid). Arbitrage condition (post-fee):"))
    s.append(math_block("(P_yes_ask + P_no_ask) · (1 + f) < $1"))
    s.append(body("Equivalently:"))
    s.append(math_block("P_yes_ask + P_no_ask < 1 / (1 + f)"))
    s.append(body("At f = 0.0075, threshold ≈ $0.9926. Profit per share pair:"))
    s.append(math_block("π = $1 − (P_yes_ask + P_no_ask) · (1 + f)"))
    s.append(body("Maker execution (fee = 0): rest both sides at limit; if both fill:"))
    s.append(math_block("π_maker = $1 − (P_yes_rest + P_no_rest)"))

    s.append(h2("B.3  NegRisk multi-outcome rebalance"))
    s.append(body("For N-outcome NegRisk market. Buy-all-YES arb condition:"))
    s.append(math_block("Σ_i P_yes_ask(i) · (1 + f) < $1"))
    s.append(body("Buy-all-NO arb condition (equivalent to sell-all-YES):"))
    s.append(math_block("Σ_i P_yes_bid(i) > $1 + fee_buffer"))
    s.append(body("Buy-all-NO payout: (N − 1) · $1, because all NOs except the winner's pay out."))

    s.append(h2("B.4  Combinatorial covering portfolio (LP)"))
    s.append(body("Variables: x_p ≥ 0 for each position p. Payoff matrix A[j, p] ∈ {0, 1}. Cost c_p per position."))
    s.append(math_block("minimize    Σ_p  c_p · x_p"))
    s.append(math_block("subject to  Σ_p  A[j, p] · x_p  ≥  1    ∀ atomic outcomes j ∈ J"))
    s.append(math_block("x_p ≥ 0     ∀ positions p"))
    s.append(body("Arbitrage exists if optimal C* < $1 (after fee adjustment)."))
    s.append(body("Dual interpretation: y_j ≥ 0 is a probability distribution over outcomes. By strong duality, if C* < $1 then no feasible probability distribution makes the market expected-value-neutral."))

    s.append(h2("B.5  Cross-platform arbitrage"))
    s.append(body("Decimal odds d imply probability 1/d. American odds +a imply 100/(a+100); −a imply a/(a+100). Vig-free normalized probability:"))
    s.append(math_block("p_vigfree(YES) = p_implied(YES) / (p_implied(YES) + p_implied(NO))"))
    s.append(body("Edge:"))
    s.append(math_block("edge = p_vigfree(YES) − P_yes_polymarket"))
    s.append(math_block("net_edge = edge − taker_fee_polymarket − sportsbook_vig/2"))

    s.append(h2("B.6  Kelly criterion"))
    s.append(body("Full Kelly fraction of bankroll:"))
    s.append(math_block("f* = (p · b − q) / b"))
    s.append(body("where p = win probability, q = 1 − p, b = net odds (decimal − 1)."))
    s.append(body("Conservative arbitrage Kelly (with settlement-risk haircut):"))
    s.append(math_block("f_cons = kelly_fraction · kelly(0.95, 1 + edge)"))
    s.append(body("Position size = bankroll × f_cons, capped at kelly_cap_bps and floored at kelly_floor_bps."))

    s.append(h2("B.7  Fee-adjusted break-even"))
    s.append(body("Break-even edge (gross bps) required to net zero profit after fees:"))
    s.append(math_block("break_even_bps = f · 10_000 · (n_legs)"))
    s.append(body("where n_legs is the number of taker legs (each pays fee). For 2-leg taker arb at 75 bps fee:"))
    s.append(math_block("break_even_bps = 0.0075 · 10_000 · 2 = 150 bps"))
    s.append(body("For 2-leg maker arb at 0 bps fee:"))
    s.append(math_block("break_even_bps = 0 · 10_000 · 2 = 0 bps"))

    s.append(h2("B.8  Odds conversion quick-reference"))
    rows = [
        ["Decimal", "American", "Implied prob", "Polymarket $"],
        ["1.20", "−500", "0.833", "$0.83"],
        ["1.50", "−200", "0.667", "$0.67"],
        ["1.91", "−110", "0.524", "$0.52"],
        ["2.00", "+100", "0.500", "$0.50"],
        ["2.50", "+150", "0.400", "$0.40"],
        ["3.00", "+200", "0.333", "$0.33"],
        ["5.00", "+400", "0.200", "$0.20"],
        ["10.00", "+900", "0.100", "$0.10"],
    ]
    s.append(std_table(
        ["Decimal", "American", "Implied prob", "Polymarket $"],
        rows,
        col_ratios=[0.25, 0.25, 0.25, 0.25],
    ))
    s.append(caption("Table B.1 — Odds format conversion reference"))

    s.append(h2("B.9  Slippage model"))
    s.append(body("Volume-weighted average price (VWAP) for buying S shares against the ask side:"))
    s.append(math_block("VWAP = (Σ_k  p_k · min(s_k, S_remaining)) / S"))
    s.append(body("where (p_k, s_k) are price/size at ask level k. Slippage in bps:"))
    s.append(math_block("slippage_bps = (VWAP − best_ask) / best_ask · 10_000"))

    return s
