# Polymarket Sports Arbitrage Scanner

Production-grade Python implementation accompanying the masterclass guide.

## Quick Start

```bash
cd arb_scanner/
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Test API connectivity (no auth needed)
python main.py test-api

# Show current config (defaults + env vars)
python main.py show-config

# Run one scan cycle in dry-run mode
python main.py scan --once --sports NBA

# Run continuous scanner in dry-run
python main.py scan --sports NBA

# Go live (requires API keys — see below)
python main.py scan --live --sports NBA
```

## Environment Variables

```bash
# Required for live trading
export POLY_API_KEY="..."
export POLY_API_SECRET="..."
export POLY_API_PASSPHRASE="..."
export POLY_PRIVATE_KEY="0x..."          # Wallet private key (no 0x prefix in some SDK versions)
export POLY_WALLET_ADDRESS="0x..."

# Optional: faster Polygon RPC
export POLY_RPC_URL="https://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY"

# Optional: alerts
export POLY_TG_TOKEN="..."               # Telegram bot token
export POLY_TG_CHAT_ID="..."             # Telegram chat ID
export POLY_DISCORD_WEBHOOK="https://discord.com/api/webhooks/..."

# Optional: override defaults
export POLY_BANKROLL_USDC=50000
export POLY_MIN_EDGE_TAKER_BPS=75

# Optional: YAML config file
export POLY_CONFIG_PATH="./config.yaml"
```

## Module Map

| File | Purpose |
|------|---------|
| `config.py` | Configuration dataclasses + env/YAML loaders + fee constants |
| `models.py` | Domain dataclasses: Market, OrderBook, Opportunity, Position, etc. |
| `gamma_client.py` | Polymarket Gamma API client (events, markets, metadata) |
| `clob_client.py` | CLOB REST + WS clients (order books, prices, order placement) |
| `detectors.py` | Opportunity detectors: single-market, NegRisk, combinatorial, cross-platform |
| `optimizer.py` | PuLP LP solver for combinatorial covering portfolios |
| `risk.py` | Kelly sizing, exposure tracker, blacklist, slippage estimator |
| `executor.py` | Concurrent leg execution, partial-fill hedging, rollback |
| `alerts.py` | Telegram + Discord notifications |
| `scanner.py` | Main scanner loop tying everything together |
| `backtest.py` | Historical backtest framework + snapshot recorder |
| `main.py` | CLI entry point (scan, backtest, record, test-api) |

## Strategy Coverage

1. **Single-market YES+NO** (`detectors.detect_single_market_arb`)
   - The bread-and-butter strategy per the article
   - Detects when YES_ask + NO_ask < $1 (after fees)
   - Maker-preferred execution to skip taker fee

2. **NegRisk multi-outcome rebalance** (`detectors.detect_negrisk_rebalance_arb`)
   - For multi-outcome markets (e.g., "Who wins MVP?")
   - Detects when sum of YES prices drifts off $1
   - Mostly relevant for politics (per the article), included for completeness

3. **Combinatorial cross-market** (`detectors.detect_combinatorial_arb`)
   - Constructs covering portfolios across moneyline + spread + totals
   - Uses LP solver (`optimizer.solve_covering_lp`)
   - Prunes physically impossible atomic outcomes (`optimizer.is_feasible_outcome`)

4. **Cross-platform** (`detectors.detect_cross_platform_arb`)
   - Compares Polymarket prices to external sportsbook implied probs
   - Requires external sportsbook data feed (not included — bring your own)

## Fee Model

Polymarket changed its fee structure in early 2026:
- **Taker fee: 0.75%** (75 bps) — applies to market orders that cross the spread
- **Maker fee: 0%** — applies to limit orders that rest on the book

The scanner defaults to **maker-preferred execution**. The min edge thresholds:
- `min_edge_taker_bps = 75` (must clear the taker fee exactly)
- `min_edge_maker_bps = 30` (just slippage buffer, since maker fee is 0)

## Backtesting

Record live snapshots first, then backtest:

```bash
# Record 6 hours of snapshots, one every 30s
python main.py record --duration 21600 --interval 30 --snapshots ./data/snapshots

# Backtest
python main.py backtest --snapshots ./data/snapshots --bankroll 50000
```

## Architecture Notes

- **Async-first**: `httpx.AsyncClient` + `websockets` for I/O concurrency
- **Concurrent leg execution**: `asyncio.gather` for parallel order placement
- **Rate limiting**: configurable via `cfg.api.rate_limit_per_sec`
- **WS reconnection**: exponential backoff (`cfg.scanner.ws_reconnect_backoff`)
- **Risk gates**: per-event, per-day, total-exposure caps + Kelly sizing
- **Blacklist**: persistent JSON of markets to skip (UMA disputes, ambiguous resolution)

## Legal & Compliance

- Polymarket is geofenced to non-US users (US users may need to use a VPN; consult local laws)
- USDC on Polygon is the settlement currency
- Wallet security best practices:
  - Use a hardware wallet for treasury
  - Use a hot wallet with limited funds for active trading
  - Never expose `POLY_PRIVATE_KEY` in code, logs, or shell history
- Tax lot tracking: each fill is a taxable event in most jurisdictions
- This code is for educational purposes. Use at your own risk.

## Disclaimer

This software is provided "as is" without warranty of any kind. Trading
prediction markets involves significant risk, including the loss of all
capital. Past performance (via backtest) does not guarantee future results.
The authors are not responsible for any financial losses incurred through
use of this software.
