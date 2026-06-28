"""
config.py — Configuration for the Polymarket sports arbitrage scanner.

All runtime knobs live here so the rest of the codebase stays pure logic.
Load order:
    1. Defaults defined in this file
    2. Override via environment variables (POLY_* prefix)
    3. Override via YAML file at POLY_CONFIG_PATH (optional)

Usage:
    from config import load_config
    cfg = load_config()
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml


# ─────────────────────────────────────────────────────────────────────────────
# Default constants — conservative production defaults
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_MIN_EDGE_BPS = 75          # 0.75% — covers the 0.75% taker fee exactly
DEFAULT_MIN_EDGE_MAKER_BPS = 30    # 0.30% — maker fee is 0, so threshold is just slippage buffer
DEFAULT_MAX_POSITION_USDC = 5_000  # per opportunity
DEFAULT_MAX_GAME_EXPOSURE_USDC = 15_000
DEFAULT_MAX_DAILY_EXPOSURE_USDC = 100_000
DEFAULT_MIN_LIQUIDITY_USDC = 5_000  # each side must have ≥ this much depth at top 5 levels
DEFAULT_POLL_INTERVAL_SEC = 5.0     # sports: 5s polling; in-play: 1s via websocket
DEFAULT_WS_RECONNECT_BACKOFF_SEC = [1, 2, 5, 10, 30, 60]

# Polymarket fee structure (post early-2026 change)
# Sports category taker fee. Maker fee = 0 across all categories.
TAKER_FEE_BPS = 75                 # 0.75%
MAKER_FEE_BPS = 0

# Kelly safety multiplier — bet 25% of full Kelly to dampen variance
KELLY_FRACTION = 0.25


# ─────────────────────────────────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ApiConfig:
    """Polymarket API endpoints and credentials."""
    gamma_base_url: str = "https://gamma-api.polymarket.com"
    clob_base_url: str = "https://clob.polymarket.com"
    ws_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws"

    # CLOB auth — see py-clob-client docs for key generation
    # NEVER commit real keys. Use env vars.
    api_key: Optional[str] = None           # POLY_API_KEY
    api_secret: Optional[str] = None        # POLY_API_SECRET
    api_passphrase: Optional[str] = None    # POLY_API_PASSPHRASE

    # Wallet (Polygon) — for order signing
    private_key: Optional[str] = None       # POLY_PRIVATE_KEY (hex, no 0x)
    wallet_address: Optional[str] = None    # POLY_WALLET_ADDRESS

    # Optional: Alchemy/Infura RPC for faster Polygon reads
    rpc_url: str = "https://polygon-rpc.com"

    # Rate limits — Polymarket CLOB soft limit ~10 req/s
    rate_limit_per_sec: float = 8.0
    max_concurrent_requests: int = 16


@dataclass
class ScannerConfig:
    """Opportunity detection thresholds."""
    # Edge thresholds (in basis points)
    min_edge_taker_bps: int = DEFAULT_MIN_EDGE_BPS
    min_edge_maker_bps: int = DEFAULT_MIN_EDGE_MAKER_BPS
    min_edge_negrisk_bps: int = 100  # NegRisk rebalance needs higher threshold (slower execution)

    # Liquidity filters
    min_liquidity_usdc: float = DEFAULT_MIN_LIQUIDITY_USDC
    min_depth_levels: int = 3        # require ≥3 price levels on each side

    # Market filters
    sports_only: bool = True
    resolve_within_hours: int = 12   # only markets resolving in next 12h (daily sports cadence)
    exclude_markets: List[str] = field(default_factory=list)  # blacklisted condition IDs

    # Polling
    poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC
    in_play_poll_interval_sec: float = 1.0
    ws_reconnect_backoff: List[float] = field(
        default_factory=lambda: list(DEFAULT_WS_RECONNECT_BACKOFF_SEC)
    )


@dataclass
class RiskConfig:
    """Position sizing and exposure limits."""
    max_position_usdc: float = DEFAULT_MAX_POSITION_USDC
    max_game_exposure_usdc: float = DEFAULT_MAX_GAME_EXPOSURE_USDC
    max_daily_exposure_usdc: float = DEFAULT_MAX_DAILY_EXPOSURE_USDC
    max_open_positions: int = 25

    # Kelly
    kelly_fraction: float = KELLY_FRACTION
    kelly_floor_bps: int = 10        # never bet less than 10bps of bankroll (dust filter)
    kelly_cap_bps: int = 500         # never bet more than 5% of bankroll on one leg

    # Bankroll
    bankroll_usdc: float = 50_000

    # Slippage modeling
    slippage_bps_per_1k_usdc: float = 5.0  # 0.05% slippage per $1k notional (sportsbooks)
    max_slippage_bps: int = 50             # hard reject if expected slippage exceeds this


@dataclass
class ExecutionConfig:
    """Order placement settings."""
    prefer_maker: bool = True              # always try to rest limit orders first
    maker_timeout_sec: float = 8.0         # how long to wait for maker fill before crossing
    taker_timeout_sec: float = 3.0
    concurrent_legs: bool = True           # place all legs of an arb simultaneously

    # Hedge logic
    hedge_on_partial_fill: bool = True
    hedge_slippage_tolerance_bps: int = 100

    # Retry
    max_retries: int = 3
    retry_backoff_sec: List[float] = field(
        default_factory=lambda: [0.5, 1.5, 4.0]
    )


@dataclass
class AlertsConfig:
    """Telegram / Discord / email notifications."""
    telegram_bot_token: Optional[str] = None  # POLY_TG_TOKEN
    telegram_chat_id: Optional[str] = None    # POLY_TG_CHAT_ID
    discord_webhook_url: Optional[str] = None # POLY_DISCORD_WEBHOOK

    # Alert filters
    min_edge_alert_bps: int = 100  # only alert on ≥1% edges
    alert_on_fill: bool = True
    alert_on_error: bool = True
    alert_on_dispute: bool = True


@dataclass
class Config:
    api: ApiConfig = field(default_factory=ApiConfig)
    scanner: ScannerConfig = field(default_factory=ScannerConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    alerts: AlertsConfig = field(default_factory=AlertsConfig)

    # Storage
    db_path: str = "data/scanner.db"
    log_path: str = "logs/scanner.log"
    snapshot_dir: str = "data/snapshots"


# ─────────────────────────────────────────────────────────────────────────────
# Loader
# ─────────────────────────────────────────────────────────────────────────────

def _from_env(cfg: Config) -> Config:
    """Pull credentials and overrides from environment variables."""
    a = cfg.api
    a.api_key = os.environ.get("POLY_API_KEY", a.api_key)
    a.api_secret = os.environ.get("POLY_API_SECRET", a.api_secret)
    a.api_passphrase = os.environ.get("POLY_API_PASSPHRASE", a.api_passphrase)
    a.private_key = os.environ.get("POLY_PRIVATE_KEY", a.private_key)
    a.wallet_address = os.environ.get("POLY_WALLET_ADDRESS", a.wallet_address)
    a.rpc_url = os.environ.get("POLY_RPC_URL", a.rpc_url)

    al = cfg.alerts
    al.telegram_bot_token = os.environ.get("POLY_TG_TOKEN", al.telegram_bot_token)
    al.telegram_chat_id = os.environ.get("POLY_TG_CHAT_ID", al.telegram_chat_id)
    al.discord_webhook_url = os.environ.get("POLY_DISCORD_WEBHOOK", al.discord_webhook_url)

    cfg.risk.bankroll_usdc = float(
        os.environ.get("POLY_BANKROLL_USDC", cfg.risk.bankroll_usdc)
    )
    cfg.scanner.min_edge_taker_bps = int(
        os.environ.get("POLY_MIN_EDGE_TAKER_BPS", cfg.scanner.min_edge_taker_bps)
    )
    return cfg


def _from_yaml(cfg: Config, path: str) -> Config:
    """Layer YAML overrides on top of existing config."""
    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}

    # Simple top-level merge for nested dataclasses
    for section_name, section_vals in data.items():
        if not hasattr(cfg, section_name):
            continue
        section = getattr(cfg, section_name)
        for k, v in section_vals.items():
            if hasattr(section, k):
                setattr(section, k, v)
    return cfg


def load_config(yaml_path: Optional[str] = None) -> Config:
    """Load config in order: defaults → env → yaml (if provided)."""
    cfg = Config()
    cfg = _from_env(cfg)
    if yaml_path is None:
        yaml_path = os.environ.get("POLY_CONFIG_PATH")
    if yaml_path and os.path.exists(yaml_path):
        cfg = _from_yaml(cfg, yaml_path)
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# Fee helpers
# ─────────────────────────────────────────────────────────────────────────────

def taker_fee_rate() -> float:
    """Return taker fee as a fraction (0.0075 = 0.75%)."""
    return TAKER_FEE_BPS / 10_000


def maker_fee_rate() -> float:
    """Return maker fee as a fraction (0.0 = 0%)."""
    return MAKER_FEE_BPS / 10_000


if __name__ == "__main__":
    # Smoke test
    c = load_config()
    print(f"Bankroll: ${c.risk.bankroll_usdc:,.0f}")
    print(f"Min edge (taker): {c.scanner.min_edge_taker_bps} bps")
    print(f"Taker fee: {TAKER_FEE_BPS} bps ({taker_fee_rate()*100:.2f}%)")
    print(f"Maker fee: {MAKER_FEE_BPS} bps ({maker_fee_rate()*100:.2f}%)")
    print(f"Kelly fraction: {c.risk.kelly_fraction}")
