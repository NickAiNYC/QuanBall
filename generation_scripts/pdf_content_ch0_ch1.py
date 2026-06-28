"""
pdf_content_ch0_ch1.py — Chapter 0 (Why Sports, Not Politics) and Chapter 1 (Core Concepts & Math).

Returns lists of ReportLab flowables. Imported by generate_pdf.py.
"""
from pdf_helpers import (
    h1, h2, h3, h4, body, bullet, numbered, kicker, math_block,
    callout, warning, info, key_insight, code_block, std_table, caption,
    hr, soft_break, chapter_break, ACCENT_EMERALD, ACCENT_AMBER,
    BODY, BODY_TIGHT,
)
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle, KeepTogether
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER


# ─────────────────────────────────────────────────────────────────────────────
# CHAPTER 0 — Why Sports, Not Politics
# ─────────────────────────────────────────────────────────────────────────────

def chapter_0():
    s = []
    s.append(kicker("Chapter 0 · Framing"))
    s.append(h1("Why Sports, Not Politics"))
    s.append(body(
        "Every new arbitrage developer who lands on Polymarket points their "
        "scanner at the same target first: politics. Elections, confirmation "
        "hearings, geopolitical markets. The instinct is rational — those are "
        "the markets with eight-figure volume headlines, the markets whose "
        "screenshots go viral on Crypto Twitter, the markets the platform "
        "itself promotes on its homepage. This chapter argues that the instinct "
        "is wrong, and that the wallets quietly compounding month after month "
        "are pointed somewhere else entirely. We will back the argument with "
        "data from a year-long academic measurement of Polymarket arbitrage, "
        "explain why the structural composition of sports flow keeps producing "
        "repeatable edges, and end with the operational implication: your "
        "scanner architecture should be optimized for the nightly cadence of "
        "professional sports, not the once-a-year cadence of an election cycle."
    ))

    s.append(h2("0.1  What the data actually shows"))
    s.append(body(
        "The clearest measurement of Polymarket arbitrage activity to date is "
        "the paper <i>Arbitrage Opportunities on Polymarket</i> (arXiv:2508.03474), "
        "which analyzes roughly a full year of platform-wide price data and "
        "tracks which opportunities real wallets exploited, not just which "
        "ones existed in theory. Three findings from that paper reframe the "
        "entire strategy space."
    ))
    s.append(body(
        "<b>Finding 1 — Politics has the fattest single payouts.</b> The largest "
        "individual arbitrage conditions the paper measured were predominantly "
        "in politics, mostly inside multi-outcome NegRisk markets tied to the "
        "2024 US election cycle. Billions of dollars of volume, thousands of "
        "conditions, prices moving every hour. When new developers read about "
        "Polymarket arbitrage, this is the picture they form in their head."
    ))
    s.append(body(
        "<b>Finding 2 — Sports has the most opportunities by count.</b> Inside "
        "multi-outcome markets the paper measured around one hundred arbitrage "
        "opportunities per market on average, and the biggest outliers sat in "
        "sports. The same nightly cadence that produces thin per-opportunity "
        "edges also produces enormous opportunity counts. Politics gives you a "
        "few fat conditions per cycle; sports gives you a hundred thin "
        "conditions per game, every night, across a dozen leagues."
    ))
    s.append(body(
        "<b>Finding 3 — Real money was taken mostly from sports single-condition "
        "arbitrage.</b> This is the line most readers skip. The paper tracked "
        "which opportunities real wallets actually exploited, as opposed to "
        "which ones existed on paper. For single-condition arbitrage (YES and "
        "NO of one outcome drifting below or above a dollar), sports markets "
        "dominated the exploited profit so heavily that they surpassed the "
        "entire 2024 election cycle in that category. Meanwhile only about "
        "one percent of the theoretically identified election opportunities "
        "were ever exploited at all. The politics opportunities are huge on "
        "paper and mostly left on the table; the sports opportunities are "
        "smaller individually, taken constantly, and add up to more."
    ))

    s.extend(key_insight(
        "Politics gives you the screenshot. Sports gives you the paycheck. "
        "The headline numbers will always point at elections because that is "
        "where the volume photo-ops are. The wallets quietly printing month "
        "after month are pointed at the games."
    ))

    s.append(h2("0.2  Politics arbitrage is a seasonal market"))
    s.append(body(
        "The fat political numbers in the paper came from one window: the "
        "election. Elections do not happen every week. You get a presidential "
        "cycle, a few primaries, the occasional geopolitical market, then "
        "long stretches of nothing. A scanner pointed at politics waits, and "
        "waits, and waits. Capital sits cold while you wait for the next "
        "headline to create enough volatility to throw prices off a dollar. "
        "Idle capital earns nothing."
    ))
    s.append(body(
        "This is the trap. You optimized your entire bot for the loudest "
        "market on the platform, and that market only pays a few weeks a "
        "year. Event-driven means seasonal; seasonal means idle. The "
        "operational cost of running a trading system (VPS, monitoring, "
        "developer attention, capital lockup) does not disappear during the "
        "idle months. A politics-only scanner carries 100% of its "
        "infrastructure cost against a fraction of the year of revenue."
    ))

    s.append(h2("0.3  Sports is the nightly edge"))
    s.append(body(
        "Now look at the other side. NBA tonight. NFL on Sunday. Soccer "
        "every day across a dozen leagues. Tennis, MMA, the whole calendar. "
        "Every single night a fresh batch of markets opens, fills with retail "
        "flow, and resolves within hours. Politics gives you one giant "
        "volatile window a year. Sports gives you a new volatile window every "
        "night. That is the difference between a strategy that prints in "
        "bursts and one that prints on a schedule."
    ))
    s.append(body(
        "Small edge, many shots, every night — that is the compounding game, "
        "and sports is built for it. The mathematical edge per opportunity is "
        "smaller in sports than in politics, but the law of large numbers "
        "applies cleanly because the opportunity count is so high. Variance of "
        "monthly PnL drops fast when you take a hundred small edges instead "
        "of two large ones."
    ))

    s.append(h2("0.4  Two different arb types live in two different places"))
    s.append(body(
        "This is the part most developers skip past, and it is where running "
        "one bot pointed at one market type leaves half the edge on the floor. "
        "There are two structurally different arbitrage types on Polymarket, "
        "and they concentrate in different market sectors."
    ))

    s.append(body(
        "<b>Single-condition arbitrage</b> — YES and NO of one outcome summing "
        "below or above a dollar. This is the high-frequency, every-night "
        "game. Per the paper, this profit concentrates in sports. Point a "
        "single-condition YES+NO scanner at the daily sports flow for your "
        "bread and butter."
    ))

    s.append(body(
        "<b>Within-market rebalancing arbitrage</b> — the sum of all YES tokens "
        "across a multi-outcome NegRisk market drifting off a dollar. The "
        "paper found this profit concentrated heavily in politics. Sports was "
        "almost absent from it. So when a real event window opens — an "
        "election, a primary, a confirmation fight — turn on a NegRisk "
        "rebalancing scanner pointed at politics. Different market, different "
        "arb, different target."
    ))

    s.extend(key_insight(
        "One bot pointed at one market type leaves half the edge on the floor. "
        "Match the scanner to the market type: single-condition YES+NO on the "
        "daily sports flow, NegRisk rebalancing on politics only when an event "
        "window opens."
    ))

    s.append(h2("0.5  Why sports stays inefficient"))
    s.append(body(
        "The deeper reason sports keeps paying is who trades it. Politics "
        "arbitrage gets picked over by smart money: quants, funds, and bot "
        "squads all camp the election. Sports gets retail. People bet their "
        "team with their heart. They pile into a YES on emotion the second "
        "their guy scores. Then an injury hits, a ref call lands, momentum "
        "flips, and the price lags the new reality for a few seconds while "
        "the order book catches up. That lag is your gap."
    ))
    s.append(body(
        "The paper even found sports markets are often overvalued, with long "
        "opportunities dominating — a sign the crowd keeps overpaying one "
        "side. And the mispricing is not small. Median profit per dollar "
        "across these single-condition opportunities sat around sixty cents "
        "in the pre-fee measurement window. That is not a three-cent skim; "
        "that is a market that is openly wrong, over and over, in a place "
        "nobody serious is watching."
    ))
    s.append(body(
        "One caveat the paper itself flags: that sixty-cent figure was "
        "measured before Polymarket introduced fees. The mispricing is still "
        "there. What changed is what you net after you trade it. We cover the "
        "fee math in Chapter 1 and the maker-versus-taker workaround in "
        "Chapter 4."
    ))

    s.append(h2("0.6  The 2026 fee change and the maker pivot"))
    s.append(body(
        "Sports received a taker fee in early 2026, and most categories "
        "followed. The opportunities are still where the data says they are "
        "(sports, every night), but you cannot simply take them anymore. Take "
        "the gap as a taker and the fee bites hardest near 50/50, exactly "
        "where these sports gaps sit. A 0.75% taker fee on both legs of a "
        "YES+NO arb at 50/50 prices eats 1.5 cents per dollar of payout, "
        "which is more than many sports gaps gross."
    ))
    s.append(body(
        "The fix is to capture them as a maker. Rest a limit order, get "
        "filled, pay zero. The edge the paper identified is still real; you "
        "just have to collect it the right way now. This is also why the "
        "default min-edge thresholds in the code accompanying this guide are "
        "split: 75 bps for taker execution (must clear the fee exactly) and "
        "30 bps for maker execution (only need a slippage buffer, since fee "
        "is zero)."
    ))

    s.append(h2("0.7  How to actually point your scanner"))
    s.append(body("Concrete setup, no fluff:"))
    s.append(bullet(
        "<b>Filter the CLOB for sports markets resolving today.</b> You want "
        "fresh, high-turnover books, not stale weeklies. The code defaults to "
        "a 12-hour resolution window."
    ))
    s.append(bullet(
        "<b>Watch the YES+NO sum on single conditions.</b> Flag the moment "
        "it drifts past your threshold. With new taker fees peaking near "
        "50/50, set the threshold higher in coin-flip markets than you would "
        "have a year ago."
    ))
    s.append(bullet(
        "<b>Be the maker, not the taker.</b> Rest your limit orders into the "
        "gap instead of crossing the spread. As a maker you pay zero fee and "
        "the threshold math goes back in your favor."
    ))
    s.append(bullet(
        "<b>Bias toward the overvalued side.</b> Sports runs rich, so the "
        "short / sell-above-a-dollar leg shows up more than people expect."
    ))
    s.append(bullet(
        "<b>Size for liquidity.</b> Sports books are thinner than the "
        "election was, so your fills are smaller. Do not model election-size "
        "depth onto a Tuesday NBA game."
    ))
    s.append(bullet(
        "<b>Run it every night.</b> The whole point of sports is frequency. "
        "A scanner that only wakes up for elections is a politics bot wearing "
        "a sports jersey."
    ))

    s.append(h2("0.8  How to read this guide"))
    s.append(body(
        "The remainder of this guide is structured for a working quant "
        "developer who wants both the math and the code. <b>Chapter 1</b> is "
        "the formal mathematics: implied probabilities, overround, the four "
        "arbitrage conditions (single-market, multi-outcome rebalance, "
        "combinatorial covering, cross-platform), fee impact, and the "
        "risk-free versus near-risk-free distinction. <b>Chapter 2</b> covers "
        "the Polymarket API stack (Gamma, CLOB REST, CLOB WebSocket) and how "
        "to discover and group related markets on one event. <b>Chapter 3</b> "
        "is the full scanner implementation with line-by-line code listings "
        "for twelve production modules. <b>Chapter 4</b> covers operational "
        "hardening: low-latency setup, slippage modeling, in-play windows, "
        "monitoring, scaling, and compliance. <b>Chapter 5</b> closes with "
        "edge maintenance, failure modes, and hybrid strategies. Two "
        "appendices follow: a code module index and a condensed mathematical "
        "reference."
    ))
    s.append(body(
        "All Python code shown in this PDF is delivered as runnable modules "
        "in the companion package. The PDF is the theory and walkthrough; "
        "the modules are the implementation. Read them in parallel."
    ))

    s.append(chapter_break())
    return s


# ─────────────────────────────────────────────────────────────────────────────
# CHAPTER 1 — Core Concepts & Math
# ─────────────────────────────────────────────────────────────────────────────

def chapter_1():
    s = []
    s.append(kicker("Chapter 1 · Mathematics"))
    s.append(h1("Core Concepts & Mathematics"))
    s.append(body(
        "This chapter develops the formal mathematics of prediction-market "
        "arbitrage from first principles. We start with the microstructure of "
        "binary outcome tokens on Polymarket, derive the implied probability "
        "and overround formulas, then build up four distinct arbitrage "
        "conditions in order of increasing complexity: single-market YES+NO "
        "arbitrage, multi-outcome NegRisk rebalancing, combinatorial "
        "cross-market covering portfolios, and cross-platform arbitrage "
        "against traditional sportsbooks. We close with a rigorous treatment "
        "of the early-2026 fee regime and a taxonomy of which strategies are "
        "truly risk-free versus merely edge-adjusted."
    ))

    s.append(h2("1.1  Prediction market microstructure"))
    s.append(body(
        "Polymarket is a centralized limit order book (CLOB) for binary "
        "outcome tokens settled on the Polygon blockchain. Each market poses "
        "a yes/no question — for example, <i>Will the Lakers defeat the "
        "Celtics on January 15?</i> — and mints two ERC-1155 tokens: a YES "
        "token and a NO token. The collateral is USDC on Polygon. At "
        "resolution, exactly one token redeems for $1 of USDC and the other "
        "redeems for $0. The settlement logic uses the UMA optimistic oracle "
        "for dispute resolution."
    ))
    s.append(body(
        "The two-outcome redemption rule has a critical mathematical "
        "consequence: one YES token plus one NO token is always worth exactly "
        "$1, regardless of outcome. This is the foundation of every "
        "arbitrage strategy on the platform. If you can acquire one share of "
        "each side for a total cost strictly less than $1 (after fees), you "
        "have locked in a guaranteed profit. The art is in finding "
        "situations where the market lets you do this, and the rest of this "
        "chapter formalizes when and how."
    ))
    s.append(body(
        "<b>NegRisk multi-outcome markets</b> extend this structure to "
        "events with more than two mutually exclusive outcomes — for example, "
        "<i>Who wins the 2025 NBA MVP?</i> with twenty candidates. Rather "
        "than spawning twenty independent binary markets (which would each "
        "need their own order book), Polymarket uses the NegRisk framework: "
        "a single ERC-1155 contract holds one YES token per outcome, with a "
        "shared collateral pool. Holding one share of every YES token still "
        "guarantees a $1 payout, because exactly one outcome will resolve "
        "YES. This shared-collateral property is what makes NegRisk "
        "rebalancing arbitrage possible: the sum of all YES prices should "
        "theoretically equal $1, and when it drifts, you can rebalance."
    ))

    s.append(h2("1.2  Implied probability and overround"))
    s.append(body(
        "The price of a YES token on Polymarket is a probability expressed "
        "in dollars. A YES price of $0.65 implies the market assigns a 65% "
        "probability to the YES outcome. Formally, given a YES ask price "
        "P_yes (the cost to buy one YES share) and a NO ask price P_no (the "
        "cost to buy one NO share):"
    ))
    s.append(math_block(
        "p_implied(YES) = P_yes / $1 = P_yes"
    ))
    s.append(math_block(
        "p_implied(NO)  = P_no  / $1 = P_no"
    ))
    s.append(body(
        "In a perfectly efficient market with no fees, the law of one price "
        "demands that P_yes + P_no = $1, because holding one of each "
        "guarantees a $1 payout. The <b>overround</b> (also called the vig "
        "or hold) measures how far the sum deviates from $1:"
    ))
    s.append(math_block(
        "overround = (P_yes + P_no) − $1"
    ))
    s.append(body(
        "An overround greater than zero means the market is overpriced — the "
        "sum of asks exceeds $1, so buying both sides loses money. An "
        "overround less than zero means an arbitrage exists — the sum of "
        "asks is below $1, so buying both sides locks in profit. Most of the "
        "time in a healthy two-sided market, the overround is slightly "
        "positive because of the bid-ask spread: P_yes_ask + P_no_ask = "
        "P_yes_ask + (1 − P_yes_bid) = 1 + spread_yes > 1."
    ))
    s.append(body(
        "<b>Normalized implied probabilities</b> remove the overround to "
        "recover the market's true probability estimate. Given overround "
        "r = P_yes + P_no − 1:"
    ))
    s.append(math_block(
        "p_norm(YES) = P_yes / (P_yes + P_no)"
    ))
    s.append(math_block(
        "p_norm(NO)  = P_no  / (P_yes + P_no)"
    ))
    s.append(body(
        "These normalized probabilities are what you compare against "
        "external sources (sportsbook odds, your own model) when looking for "
        "cross-platform or model-driven edges. The unnormalized prices are "
        "what you trade."
    ))

    s.append(h3("Worked example: Lakers vs Celtics moneyline"))
    s.append(body(
        "Consider an NBA moneyline market: <i>Will the Lakers defeat the "
        "Celtics?</i> The order book shows YES best ask at $0.48 and NO best "
        "ask at $0.49 (which corresponds to a YES best bid of $0.51)."
    ))
    s.append(body(
        "Implied probabilities: p(YES) = 0.48, p(NO) = 0.49. Sum = 0.97, "
        "overround = −$0.03. Normalized probabilities: p_norm(YES) = "
        "0.48 / 0.97 = 0.4948, p_norm(NO) = 0.49 / 0.97 = 0.5052. The "
        "market is essentially a coin flip with a slight lean toward the "
        "Celtics, but the unnormalized prices sum to less than $1, which "
        "means an arbitrage exists. We will compute the exact profit after "
        "fees in the next section."
    ))

    s.append(h2("1.3  Single-market arbitrage"))
    s.append(body(
        "Single-market arbitrage is the simplest and most repeatable "
        "strategy: buy one YES and one NO of the same binary market, and if "
        "the combined cost is less than $1 after fees, you have locked in a "
        "riskless profit. Per the article framing this guide, this is the "
        "bread-and-butter strategy for sports — the high-frequency, "
        "every-night edge that real wallets exploit more than any other "
        "arbitrage type on Polymarket."
    ))

    s.append(h3("Arbitrage condition"))
    s.append(body(
        "Let P_yes_ask be the best ask price for YES, P_yes_bid the best bid "
        "for YES. The cost to buy one YES share is P_yes_ask. The cost to "
        "buy one NO share is the NO ask, which equals 1 − P_yes_bid (because "
        "buying NO at the NO ask is equivalent to selling YES at the YES "
        "bid, modulo minting mechanics). Define the gross cost:"
    ))
    s.append(math_block(
        "C_gross = P_yes_ask + (1 − P_yes_bid) = 1 + spread_yes"
    ))
    s.append(body(
        "Without fees, this gross cost always equals 1 + spread_yes, which "
        "is greater than $1 in any market with a positive bid-ask spread. "
        "The arbitrage only appears when the spread inverts — that is, when "
        "P_yes_bid > P_yes_ask, which cannot happen in a single order book, "
        "OR when the YES and NO prices come from different liquidity sources "
        "that have not yet synchronized. The latter is what creates sports "
        "single-market arbitrage in practice: a taker crosses the spread on "
        "one side, a market maker pulls quotes on the other, and for a few "
        "seconds the best bid for YES exceeds the best ask for NO "
        "(equivalently, the sum P_yes_ask + P_no_ask drops below $1)."
    ))
    s.append(body(
        "Formally, the arbitrage condition (before fees) is:"
    ))
    s.append(math_block(
        "P_yes_ask + P_no_ask < $1"
    ))
    s.append(body(
        "Including the taker fee f (currently 0.0075 = 75 bps per leg), the "
        "net cost per share pair is:"
    ))
    s.append(math_block(
        "C_net = (P_yes_ask + P_no_ask) · (1 + f)"
    ))
    s.append(body(
        "And the arbitrage exists when C_net < $1, equivalently when "
        "(P_yes_ask + P_no_ask) < 1 / (1 + f). At f = 0.0075, the "
        "threshold sum is approximately $0.9926 — meaning the raw YES+NO "
        "sum must drop below roughly 99.26 cents to clear fees as a taker. "
        "The guaranteed profit per share pair is:"
    ))
    s.append(math_block(
        "π = $1 − C_net = $1 − (P_yes_ask + P_no_ask) · (1 + f)"
    ))

    s.append(h3("Position sizing for equal payout"))
    s.append(body(
        "If you buy N_yes shares of YES at P_yes_ask and N_no shares of NO "
        "at P_no_ask, the payout is max(N_yes, N_no) · $1 (whichever side "
        "wins). To guarantee equal payout regardless of outcome, you need "
        "N_yes = N_no = N. Total cost is then N · (P_yes_ask + P_no_ask) · "
        "(1 + f), guaranteed payout is N · $1, and profit scales linearly "
        "with N. The maximum N is constrained by the smaller of the two "
        "sides' available depth at the ask."
    ))

    s.append(h3("Maker execution: zero-fee arbitrage"))
    s.append(body(
        "The early-2026 fee change introduced a 0.75% taker fee but kept "
        "the maker fee at zero. As a maker, you rest limit orders on the "
        "book rather than crossing the spread. If both your YES bid and "
        "your NO bid (equivalently, your YES ask at 1 − P_no_bid) fill, the "
        "total cost is:"
    ))
    s.append(math_block(
        "C_maker = P_yes_bid_rested + P_no_bid_rested"
    ))
    s.append(body(
        "with zero fee. If you can rest both sides such that "
        "P_yes_bid_rested + P_no_bid_rested < $1, every pair that fills "
        "locks in pure profit. The trade-off is execution risk: maker orders "
        "may not fill (especially in fast-moving sports markets), and the "
        "window during which the inverted spread persists may close before "
        "both legs fill. The default scanner configuration prefers maker "
        "execution with an 8-second timeout, falling back to taker if the "
        "maker order has not filled by then."
    ))

    s.append(h3("Worked example with fees"))
    s.append(body(
        "Returning to the Lakers/Celtics moneyline: YES ask = $0.48, NO ask "
        "= $0.49 (so YES bid = $0.51, NO bid = $0.52). Sum of asks = $0.97."
    ))
    s.append(body(
        "<b>Taker path:</b> C_net = $0.97 × (1 + 0.0075) = $0.97 × 1.0075 "
        "= $0.9773. Profit per share pair = $1 − $0.9773 = $0.0227. On "
        "$1,000 notional (about 1,031 share pairs), gross profit ≈ $23.40. "
        "Net of fees that is the realized profit, since fees are already "
        "in C_net. Edge in basis points: $0.0227 / $0.97 = 234 bps gross, "
        "161 bps net of fees."
    ))
    s.append(body(
        "<b>Maker path:</b> Rest a YES bid at $0.47 and a NO bid at $0.48 "
        "(equivalently, a YES ask at $0.52). If both fill, C_maker = $0.47 "
        "+ $0.48 = $0.95. Profit per share pair = $1 − $0.95 = $0.05. Edge "
        "= 526 bps. The maker path captures roughly 2.2× the taker edge on "
        "the same opportunity, but you must wait for both legs to fill and "
        "you carry the risk that only one fills before the spread closes."
    ))

    s.append(h2("1.4  Multi-outcome NegRisk rebalancing arbitrage"))
    s.append(body(
        "NegRisk markets have N ≥ 3 mutually exclusive outcomes. Each "
        "outcome has its own YES token, and the prices should theoretically "
        "sum to $1 because holding one share of every YES guarantees $1 "
        "payout (exactly one outcome wins). When the sum drifts off $1, "
        "rebalancing arbitrage becomes possible."
    ))

    s.append(h3("Buy-all-YES arb condition"))
    s.append(body(
        "If Σ_i P_yes_ask(i) < $1, you can buy one share of every YES "
        "and lock in a guaranteed $1 payout. Including fees:"
    ))
    s.append(math_block(
        "C_net_buy_all = (Σ_i P_yes_ask(i)) · (1 + f)"
    ))
    s.append(math_block(
        "π_buy_all = $1 − C_net_buy_all"
    ))
    s.append(body(
        "The arbitrage exists when Σ_i P_yes_ask(i) < 1 / (1 + f). "
        "Sizing is constrained by the minimum available ask depth across "
        "all N outcomes, because you must buy equal quantities of each to "
        "guarantee the $1 payout."
    ))

    s.append(h3("Buy-all-NO arb condition (sell-all-YES equivalent)"))
    s.append(body(
        "If Σ_i P_yes_bid(i) > $1, equivalently Σ_i (1 − P_yes_bid(i)) "
        "< N − 1, the YES side is collectively overpriced. Polymarket "
        "does not support native shorting, but you can achieve the "
        "equivalent by buying NO on every outcome. The cost of buying one "
        "NO share on each outcome is Σ_i (1 − P_yes_bid(i)) = N − Σ_i "
        "P_yes_bid(i). The payout is (N − 1) · $1, because all NOs except "
        "the winner's NO pay out. Profit:"
    ))
    s.append(math_block(
        "π_sell_all = (N − 1) − (N − Σ P_yes_bid) · (1 + f) "
        "= Σ P_yes_bid − 1 − fee_term"
    ))
    s.append(body(
        "The arbitrage exists when Σ_i P_yes_bid(i) > 1 + fee_buffer. "
        "Per the article, this NegRisk rebalancing profit concentrates "
        "heavily in politics and is almost absent from sports — so this "
        "detector is included in the code for completeness but is not the "
        "primary sports edge."
    ))

    s.append(h2("1.5  Combinatorial cross-market arbitrage"))
    s.append(body(
        "Combinatorial arbitrage is the deepest edge in the strategy space "
        "and the one most readers underuse. The idea: a single sports game "
        "spawns multiple logically dependent markets — moneyline, spread, "
        "totals, player props, quarter lines. These markets share an "
        "underlying event, so their outcomes are not independent. By "
        "constructing a portfolio of positions across these markets, you "
        "can sometimes find a basket that pays at least $1 in every "
        "possible atomic outcome, for a total cost below $1."
    ))

    s.append(h3("Atomic outcome enumeration"))
    s.append(body(
        "Consider an NBA game with three binary markets: moneyline "
        "(Lakers vs Celtics), spread (Lakers −3.5), and total (O/U 220.5). "
        "Naive cross-product gives 2 × 2 × 2 = 8 atomic outcomes, but not "
        "all are physically possible. For example, the combination "
        "<i>Lakers win AND Lakers cover −3.5 AND under 220.5</i> is "
        "physically possible (Lakers win by 4+ in a low-scoring game), but "
        "<i>Celtics win AND Lakers cover −3.5</i> is impossible (if "
        "Celtics win, Lakers cannot have covered a negative spread)."
    ))
    s.append(body(
        "Formally, an <b>atomic outcome</b> j is a fully-specified "
        "combination of results across all related markets: j ∈ "
        "{win/loss, cover/no-cover, over/under, ...}. The set of feasible "
        "atomic outcomes J is the subset of the cross-product that is "
        "physically possible given the sport's rules. Pruning infeasible "
        "outcomes is critical: if you do not prune, the LP solver will "
        "waste effort covering outcomes that can never occur and may "
        "report arbitrage that does not exist in reality."
    ))

    s.append(h3("Payoff matrix"))
    s.append(body(
        "Define the set of candidate positions P. For each market m in the "
        "event, you can either buy YES or buy NO, giving two candidate "
        "positions per market: P = {(m_1, YES), (m_1, NO), (m_2, YES), "
        "(m_2, NO), ...}. For each position p ∈ P and each atomic outcome "
        "j ∈ J, define the payoff:"
    ))
    s.append(math_block(
        "A[j, p] = 1  if position p wins in outcome j, else 0"
    ))
    s.append(body(
        "The cost of position p is its best ask price c_p (for YES) or "
        "(1 − best_bid) (for NO). The covering portfolio problem is then a "
        "linear program."
    ))

    s.append(h3("LP formulation"))
    s.append(body(
        "Variables: x_p ≥ 0 for each position p (number of shares to buy).")
    )
    s.append(math_block(
        "minimize    Σ_p  c_p · x_p"
    ))
    s.append(math_block(
        "subject to  Σ_p  A[j, p] · x_p  ≥  1     for each atomic outcome j ∈ J"
    ))
    s.append(math_block(
        "x_p ≥ 0     for each position p"
    ))
    s.append(body(
        "If the optimal cost C* is less than $1 (after fee adjustment), an "
        "arbitrage exists. The guaranteed profit per unit of covering is "
        "$1 − C*. The LP finds the minimum-cost basket that pays at least "
        "$1 in every feasible atomic outcome — it is the formal definition "
        "of a riskless covering portfolio."
    ))
    s.append(body(
        "The dual of this LP has an elegant interpretation: dual variables "
        "y_j ≥ 0 represent a probability distribution over atomic outcomes. "
        "By strong duality, if C* < $1 then there exists no probability "
        "distribution over outcomes under which the current prices are "
        "expected-value-neutral. Equivalently, the market is collectively "
        "mispriced relative to any feasible outcome distribution."
    ))

    s.append(h3("Worked NBA example"))
    s.append(body(
        "Lakers vs Celtics. Markets: (1) Moneyline: Lakers YES @ $0.55, "
        "NO @ $0.45. (2) Spread Lakers −3.5: YES @ $0.48, NO @ $0.52. "
        "(3) Total O/U 220.5: Over @ $0.50, Under @ $0.50."
    ))
    s.append(body(
        "Feasible atomic outcomes (after pruning impossible combinations): "
        "(a) Lakers win by 4+ → moneyline=Lakers, spread=Lakers cover, "
        "total either; (b) Lakers win by 1-3 → moneyline=Lakers, "
        "spread=Celtics cover, total either; (c) Celtics win → "
        "moneyline=Celtics, spread=Celtics cover, total either. Total of "
        "6 feasible atomic outcomes (3 win-margin scenarios × 2 total "
        "scenarios)."
    ))
    s.append(body(
        "Running the LP solver (see <code>optimizer.py</code>) on this "
        "snapshot would return the minimum-cost basket — for example, "
        "buying moneyline-Lakers YES, spread-Celtics YES, and under-220.5 "
        "YES, with the share allocation that minimizes total cost while "
        "guaranteeing ≥$1 in each of the 6 outcomes. Whether an actual "
        "arbitrage exists depends on the live prices at scan time; the "
        "above snapshot is illustrative."
    ))

    s.append(h2("1.6  Cross-platform arbitrage"))
    s.append(body(
        "Cross-platform arbitrage compares Polymarket prices to those of "
        "traditional sportsbooks (Pinnacle, Betfair, Circa, DraftKings). "
        "The two venue types have different microstructure: Polymarket is "
        "an open CLOB with a 0.75% taker fee; sportsbooks are quote-driven "
        "with vig baked into the odds. The strategy: identify a market "
        "where Polymarket's implied probability diverges from a sportsbook's "
        "vig-free implied probability by more than the combined fee buffer."
    ))

    s.append(h3("Odds conversion"))
    s.append(body(
        "Sportsbook odds come in three formats. Decimal odds d imply a "
        "probability of 1/d. American odds +a imply probability "
        "100/(a+100); American odds −a imply probability a/(a+100). "
        "Polymarket prices are already decimal: P_yes = decimal odds d_yes "
        "= 1/p_yes. To remove vig from a sportsbook line, normalize:"
    ))
    s.append(math_block(
        "p_vigfree(YES) = p_implied(YES) / (p_implied(YES) + p_implied(NO))"
    ))
    s.append(body(
        "For a typical NBA spread at Pinnacle with −110 on both sides, "
        "p_implied = 0.524 on each side, sum = 1.048, so the vig is 4.8% "
        "and p_vigfree = 0.5 on each side. This normalized probability is "
        "what you compare against the Polymarket price."
    ))

    s.append(h3("Edge calculation"))
    s.append(body(
        "If Polymarket YES price P_yes is below the sportsbook's vig-free "
        "probability p_vigfree by more than the fee buffer, you have an "
        "edge by buying YES on Polymarket (the cheaper venue) and either "
        "laying the bet on the sportsbook or simply taking the Polymarket "
        "side as a directional bet (unhedged, since the sportsbook side "
        "locks capital at the sportsbook)."
    ))
    s.append(math_block(
        "edge = p_vigfree − P_yes"
    ))
    s.append(math_block(
        "net_edge = edge − taker_fee − sportsbook_vig/2"
    ))
    s.append(body(
        "Settlement risk is the operational difference: Polymarket settles "
        "via UMA oracle, which can take hours to days for disputed markets, "
        "while sportsbooks typically grade within hours of game completion. "
        "Capital on the losing side is locked until both venues settle, "
        "which affects capital efficiency and should be priced into the "
        "edge threshold."
    ))

    s.append(h2("1.7  Fee structure impact analysis"))
    s.append(body(
        "Polymarket's early-2026 fee change is the single most important "
        "structural shift in the platform's history for arbitrage "
        "operators. Pre-fee, the breakeven threshold for single-market "
        "arbitrage was simply P_yes_ask + P_no_ask < $1. Post-fee, the "
        "threshold depends on execution mode."
    ))

    rows = [
        ["Taker (both legs)", "$1 / (1 + 0.0075) ≈ $0.9926", "74 bps per leg", "0.75% × 2 = 1.5% on cost"],
        ["Maker (both legs)", "$1.0000 (no fee)", "0 bps", "0% (maker fee = 0)"],
        ["Mixed maker+taker", "Depends on which leg crosses", "Asymmetric", "Half of taker fee on average"],
    ]
    s.append(std_table(
        ["Execution mode", "Break-even sum threshold", "Implied edge per leg", "Total fee on cost"],
        rows,
        col_ratios=[0.27, 0.30, 0.20, 0.23],
    ))
    s.append(caption("Table 1.1 — Fee break-even thresholds by execution mode (early-2026 fee regime)"))

    s.append(body(
        "The fee bites hardest near 50/50 prices, which is exactly where "
        "most sports gaps sit. A 1-cent gap at 50/50 prices is 100 bps "
        "gross, but after 75 bps × 2 = 150 bps of taker fees, you net "
        "negative 50 bps. The same 1-cent gap at 90/10 prices is also 100 "
        "bps gross but the dollar fee is identical, so it nets negative "
        "50 bps as well. The lesson: taker execution at 50/50 needs at "
        "least 1.5 cents of gap to break even, which is rare in liquid "
        "sports markets."
    ))
    s.append(body(
        "This is why maker execution became mandatory post-fee. As a "
        "maker, you pay zero fee and the threshold math resets to the "
        "pre-fee regime — any spread inversion captures profit. The "
        "trade-off is execution risk: maker orders may not fill, and the "
        "inversion window may close before both legs fill. Chapter 4 "
        "covers the operational techniques for maximizing maker fill "
        "rates."
    ))

    s.append(h2("1.8  Risk-free versus near-risk-free"))
    s.append(body(
        "Not all arbitrage is created equal. A rigorous taxonomy of risk "
        "helps you size positions correctly and avoid surprises. The four "
        "categories below span from truly riskless to merely edge-adjusted."
    ))

    s.append(h3("Category 1: Truly riskless (mathematical arbitrage)"))
    s.append(body(
        "Single-market YES+NO arb where both legs fill simultaneously, "
        "settlement is unambiguous, and no fees apply (maker execution). "
        "Example: you rest a YES bid and a NO bid that both fill within "
        "the same scan cycle on a market with a clear resolution rule "
        "(e.g., NBA moneyline). Risk: essentially zero. Position size: "
        "limited only by available depth and your bankroll."
    ))

    s.append(h3("Category 2: Near-riskless (settlement risk only)"))
    s.append(body(
        "Same as Category 1 but with non-zero settlement risk: the market "
        "could enter UMA dispute, the resolution criteria could be "
        "ambiguous (e.g., rain-delayed MLB games, NFL overtime edge "
        "cases), or the oracle could deliver an unexpected result. "
        "Position size: apply a haircut (typically 10-25% Kelly) to "
        "account for the small probability of total loss."
    ))

    s.append(h3("Category 3: Edge-adjusted (execution risk)"))
    s.append(body(
        "Combinatorial arbitrage where multiple legs must fill across "
        "multiple markets. If one leg fails to fill, you are left with "
        "unhedged directional exposure. Position size: small Kelly "
        "fraction (25%), strict execution-timeout discipline, and a "
        "rollback plan to flatten partial fills. Chapter 3 covers the "
        "execution engine that handles this."
    ))

    s.append(h3("Category 4: Directional with edge (cross-platform)"))
    s.append(body(
        "Cross-platform arbitrage where you take one side on Polymarket "
        "and the other on a sportsbook. Even if the edge is positive in "
        "expectation, you carry venue risk (one venue could fail to "
        "settle), timing risk (the two venues settle at different times), "
        "and capital-lockup risk. Position size: full Kelly with a "
        "per-position cap, and only deploy capital you can afford to "
        "have locked for the full settlement window."
    ))

    s.extend(warning(
        "Settlement risk is the silent killer of arbitrage strategies. "
        "Even a 1% probability of total loss per position — say, a UMA "
        "dispute that resolves against you — turns a 100 bps expected "
        "edge into a 0 bps expected edge if your position size is the "
        "full payout. Always haircut Kelly for settlement risk, and "
        "maintain a blacklist of markets with prior disputes."
    ))

    s.append(h2("1.9  Summary"))
    s.append(body(
        "This chapter developed the four arbitrage conditions in order of "
        "complexity: single-market YES+NO sum < $1 (riskless under "
        "maker execution); multi-outcome NegRisk sum drift (riskless in "
        "theory, concentrated in politics in practice); combinatorial "
        "covering portfolio via LP (riskless if all legs fill, the "
        "deepest edge but highest execution risk); cross-platform vs "
        "sportsbooks (directional with edge, settlement and capital "
        "risks). Each condition has a precise mathematical threshold that "
        "incorporates the current fee structure. The next chapter covers "
        "the data pipeline that feeds these detectors in real time."
    ))

    s.append(chapter_break())
    return s
