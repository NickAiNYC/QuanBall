"""
main.py — Single entry point for the Polymarket sports arbitrage scanner.

Subcommands:
    scan        — Run the live scanner (default --dry-run)
    backtest    — Run backtest on saved snapshots
    record      — Record live snapshots for later backtesting
    test-api    — Quick API connectivity test
    show-config — Print current config + env detection

Examples:
    python main.py scan --dry-run --sports NBA
    python main.py scan --live --sports NBA,NFL
    python main.py record --duration 3600 --interval 30
    python main.py backtest --snapshots ./data/snapshots --bankroll 50000
    python main.py test-api
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from config import load_config, TAKER_FEE_BPS, MAKER_FEE_BPS
from scanner import Scanner, setup_logging
from backtest import run_backtest, load_snapshots, record_snapshots
from models import Sport


def cmd_scan(args):
    cfg = load_config(yaml_path=args.config)
    setup_logging(cfg, args.log_level)
    sports = [Sport(s.strip().upper()) for s in args.sports.split(",")]
    dry_run = not args.live

    async def run():
        scanner = Scanner(cfg, dry_run=dry_run, sports_filter=sports)
        await scanner.start()
        if args.once:
            opps = await scanner.scan_once()
            print(f"\nFound {len(opps)} opportunities:")
            for o in opps[:50]:
                print(f"  {o.type.value:20s} edge={o.net_edge_bps:6.0f}bps  "
                      f"cost=${o.total_cost:7.2f}  profit=${o.net_edge:6.2f}  "
                      f"event={o.event_slug}")
            await scanner.stop()
        else:
            await scanner.run_forever()

    asyncio.run(run())


def cmd_backtest(args):
    cfg = load_config(yaml_path=args.config)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    snapshots = load_snapshots(args.snapshots)
    if not snapshots:
        print("No snapshots found")
        return
    sports = [Sport(s.strip().upper()) for s in args.sports.split(",")]
    result = run_backtest(snapshots, cfg, args.bankroll, sports_filter=sports)

    print("\n" + "="*60)
    print("BACKTEST RESULTS")
    print("="*60)
    print(f"Snapshots analyzed:     {result.n_snapshots}")
    print(f"Opportunities found:    {result.n_opportunities}")
    print(f"Opportunities executed: {result.n_executed}")
    print(f"Win rate:               {result.win_rate*100:.1f}%")
    print(f"Realized PnL:           ${result.realized_pnl_usdc:,.2f}")
    print(f"Total capital deployed: ${result.total_cost_usdc:,.2f}")
    print(f"ROI:                    {result.roi_pct:.2f}%")
    print(f"Avg edge (detected):    {result.avg_edge_bps:.1f} bps")
    print(f"Avg slippage:           {result.avg_slippage_bps:.1f} bps")
    print(f"Max drawdown:           ${result.max_drawdown_usdc:,.2f}")
    print()
    print("By strategy type:")
    for t, stats in sorted(result.by_type.items()):
        roi = (stats["pnl"] / stats["cost"] * 100) if stats["cost"] > 0 else 0
        print(f"  {t:20s} n={stats['n']:4d}  "
              f"PnL=${stats['pnl']:>10.2f}  cost=${stats['cost']:>10.2f}  ROI={roi:5.2f}%")


def cmd_record(args):
    cfg = load_config(yaml_path=args.config)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(record_snapshots(cfg, args.duration, args.interval, args.snapshots))


async def _test_api():
    """Quick connectivity test for Gamma and CLOB APIs."""
    cfg = load_config()
    print("Testing Polymarket API connectivity...\n")

    from gamma_client import GammaClient
    from clob_client import CLOBRestClient

    async with GammaClient(cfg) as gamma:
        try:
            events = await gamma.list_sports_events(limit=10)
            print(f"✓ Gamma API: fetched {len(events)} sports events")
            for ev in events[:5]:
                title = ev.get("title", "")[:60]
                slug = ev.get("slug", "")[:30]
                print(f"    - {title} ({slug})")
        except Exception as e:
            print(f"✗ Gamma API failed: {e}")

    print()
    async with CLOBRestClient(cfg) as rest:
        try:
            # Pick first NBA market and fetch book
            async with GammaClient(cfg) as gamma:
                events = await gamma.fetch_sports_events_with_markets(
                    sports=[Sport.NBA], max_events=3
                )
            if not events or not events[0].markets:
                print("✗ No NBA events/markets found to test CLOB")
                return

            test_market = events[0].markets[0]
            book = await rest.get_order_book(test_market.token_id_yes)
            print(f"✓ CLOB API: fetched book for {test_market.condition_id[:12]}")
            print(f"    Question: {test_market.question[:80]}")
            print(f"    Best bid: {book.best_bid.price if book.best_bid else 'N/A'}")
            print(f"    Best ask: {book.best_ask.price if book.best_ask else 'N/A'}")
            print(f"    Spread:   {book.spread:.4f}" if book.spread else "    Spread: N/A")
            print(f"    Bid depth (5 levels): ${book.depth_usd(5)[0]:.2f}")
            print(f"    Ask depth (5 levels): ${book.depth_usd(5)[1]:.2f}")
        except Exception as e:
            print(f"✗ CLOB API failed: {e}")

    print()
    print(f"Taker fee: {TAKER_FEE_BPS} bps ({TAKER_FEE_BPS/100:.2f}%)")
    print(f"Maker fee: {MAKER_FEE_BPS} bps ({MAKER_FEE_BPS/100:.2f}%)")


def cmd_test_api(args):
    asyncio.run(_test_api())


def cmd_show_config(args):
    cfg = load_config(yaml_path=args.config)
    print("Active configuration:")
    print(f"  Bankroll:              ${cfg.risk.bankroll_usdc:,.0f}")
    print(f"  Max position:          ${cfg.risk.max_position_usdc:,.0f}")
    print(f"  Max game exposure:     ${cfg.risk.max_game_exposure_usdc:,.0f}")
    print(f"  Max daily exposure:    ${cfg.risk.max_daily_exposure_usdc:,.0f}")
    print(f"  Min edge (taker):      {cfg.scanner.min_edge_taker_bps} bps")
    print(f"  Min edge (maker):      {cfg.scanner.min_edge_maker_bps} bps")
    print(f"  Kelly fraction:        {cfg.risk.kelly_fraction}")
    print(f"  Poll interval:         {cfg.scanner.poll_interval_sec}s")
    print(f"  Resolve within hours:  {cfg.scanner.resolve_within_hours}")
    print()
    print("API credentials (from env):")
    print(f"  POLY_API_KEY:          {'✓ set' if cfg.api.api_key else '✗ not set'}")
    print(f"  POLY_API_SECRET:       {'✓ set' if cfg.api.api_secret else '✗ not set'}")
    print(f"  POLY_PRIVATE_KEY:      {'✓ set' if cfg.api.private_key else '✗ not set'}")
    print(f"  POLY_WALLET_ADDRESS:   {'✓ set' if cfg.api.wallet_address else '✗ not set'}")
    print(f"  POLY_TG_TOKEN:         {'✓ set' if cfg.alerts.telegram_bot_token else '✗ not set'}")
    print(f"  POLY_TG_CHAT_ID:       {'✓ set' if cfg.alerts.telegram_chat_id else '✗ not set'}")


def main():
    parser = argparse.ArgumentParser(
        prog="polymarket-arb",
        description="Polymarket sports arbitrage scanner",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # scan
    p_scan = sub.add_parser("scan", help="Run the live scanner")
    p_scan.add_argument("--config", type=str)
    p_scan.add_argument("--sports", type=str, default="NBA")
    p_scan.add_argument("--live", action="store_true",
                        help="Place real orders (default: dry-run)")
    p_scan.add_argument("--once", action="store_true",
                        help="Run one scan and exit")
    p_scan.add_argument("--log-level", type=str, default="INFO")
    p_scan.set_defaults(func=cmd_scan)

    # backtest
    p_bt = sub.add_parser("backtest", help="Backtest on saved snapshots")
    p_bt.add_argument("--snapshots", type=str, required=True)
    p_bt.add_argument("--bankroll", type=float, default=50_000)
    p_bt.add_argument("--sports", type=str, default="NBA")
    p_bt.add_argument("--config", type=str)
    p_bt.set_defaults(func=cmd_backtest)

    # record
    p_rec = sub.add_parser("record", help="Record live snapshots")
    p_rec.add_argument("--snapshots", type=str, default="data/snapshots")
    p_rec.add_argument("--duration", type=int, default=3600)
    p_rec.add_argument("--interval", type=int, default=30)
    p_rec.add_argument("--config", type=str)
    p_rec.set_defaults(func=cmd_record)

    # test-api
    p_test = sub.add_parser("test-api", help="Test API connectivity")
    p_test.set_defaults(func=cmd_test_api)

    # show-config
    p_cfg = sub.add_parser("show-config", help="Show current config")
    p_cfg.add_argument("--config", type=str)
    p_cfg.set_defaults(func=cmd_show_config)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
