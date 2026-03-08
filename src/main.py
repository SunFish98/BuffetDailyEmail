"""Main orchestrator for SICA (Sage Investor Council Agent) multi-agent stock analysis system."""

import asyncio
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import yaml
from dotenv import load_dotenv

from .data_collector import DataCollector
from .analysts import ALL_ANALYSTS, get_enabled_analysts
from .aggregator import Aggregator
from .email_sender import EmailSender
from .storage import HistoryTracker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config(config_path: str = "config/settings.yaml") -> dict:
    """Load configuration from YAML file."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def run_analyst(analyst_class, config: dict, market_briefing: str) -> dict:
    """Run a single analyst (used for parallel execution)."""
    analyst = analyst_class(config)
    return analyst.analyze(market_briefing)


def main(config_path: str = "config/settings.yaml", skip_email: bool = False,
         save_report: bool = True, analysts_override: list[str] | None = None):
    """Main entry point for the daily analysis pipeline.

    Args:
        config_path: Path to the settings.yaml config file.
        skip_email: If True, skip sending the email (useful for testing).
        save_report: If True, save HTML/text reports to data/ directory.
        analysts_override: If set, override config to enable only these analysts.
    """
    load_dotenv()
    start_time = time.time()

    # Verify API key for the selected provider
    from .llm_client import get_llm_provider
    provider = get_llm_provider()
    if provider == "gemini":
        if not os.getenv("GEMINI_API_KEY"):
            logger.error("GEMINI_API_KEY not set. Add it to your .env file.")
            sys.exit(1)
    else:
        if not os.getenv("ANTHROPIC_API_KEY"):
            logger.error("ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.")
            sys.exit(1)

    logger.info("=" * 60)
    logger.info("SICA — Sage Investor Council Agent")
    logger.info("=" * 60)

    # Load config
    config = load_config(config_path)

    # CLI --analysts override takes priority over config
    if analysts_override:
        config.setdefault("analysts", {})["enabled"] = analysts_override
    watchlist = config.get("watchlist", [])
    logger.info(f"Watchlist: {len(watchlist)} tickers")

    # Initialize components
    collector = DataCollector(config)
    aggregator = Aggregator(config)
    email_sender = EmailSender(config)
    history = HistoryTracker(
        db_path=config.get("history", {}).get("db_path", "data/history.db")
    )

    # ── PHASE 1: Data Collection ──
    logger.info("\n📊 PHASE 1: Collecting market data...")
    data = collector.collect_all(watchlist)
    market_briefing = collector.prepare_full_context(data)
    logger.info(f"Market briefing: {len(market_briefing)} characters")

    # ── PHASE 2: Analyst Agents ──
    logger.info("\n🧠 PHASE 2: Running analyst agents...")
    analyst_config = config.get("analysts", {})
    parallel = analyst_config.get("parallel", True)
    analyst_results = []

    # Select enabled analysts (subset or all)
    enabled_analysts = get_enabled_analysts(config)
    if not enabled_analysts:
        logger.error("No analysts enabled. Check analysts.enabled in config.")
        sys.exit(1)

    skipped = len(ALL_ANALYSTS) - len(enabled_analysts)
    if skipped > 0:
        enabled_names = [cls.name for cls in enabled_analysts]
        logger.info(f"Enabled {len(enabled_analysts)}/{len(ALL_ANALYSTS)} sages: {', '.join(enabled_names)}")

        # Auto-adjust consensus threshold if fewer analysts are active
        agg_config = config.get("aggregator", {})
        threshold = agg_config.get("consensus_threshold", 3)
        max_reasonable = max(2, (len(enabled_analysts) + 1) // 2)
        if threshold > len(enabled_analysts):
            agg_config["consensus_threshold"] = max_reasonable
            logger.info(f"  Auto-adjusted consensus threshold: {threshold} → {max_reasonable} (fewer analysts)")

    if parallel:
        logger.info(f"Running {len(enabled_analysts)} analysts in parallel...")
        with ThreadPoolExecutor(max_workers=len(enabled_analysts)) as executor:
            futures = {
                executor.submit(run_analyst, cls, config, market_briefing): cls.name
                for cls in enabled_analysts
            }
            for future in as_completed(futures):
                analyst_name = futures[future]
                try:
                    result = future.result()
                    analyst_results.append(result)
                    picks = len(result.get("top_picks", []))
                    logger.info(f"  ✓ {analyst_name}: {picks} picks")
                except Exception as e:
                    logger.error(f"  ✗ {analyst_name} failed: {e}")
                    analyst_results.append({
                        "analyst": analyst_name,
                        "error": str(e),
                        "top_picks": [],
                        "avoid_list": [],
                        "key_observations": [f"Analysis failed: {e}"],
                        "market_outlook": "Analysis unavailable",
                    })
    else:
        for analyst_class in enabled_analysts:
            logger.info(f"  Running {analyst_class.name}...")
            result = run_analyst(analyst_class, config, market_briefing)
            analyst_results.append(result)
            picks = len(result.get("top_picks", []))
            logger.info(f"  ✓ {analyst_class.name}: {picks} picks")

    # ── PHASE 3: Historical Tracking & Scorecard ──
    logger.info("\n📈 PHASE 3: Loading historical accuracy...")
    today = datetime.now().strftime("%Y-%m-%d")

    # Load scorecard from prior history BEFORE aggregation so it can weight opinions
    scorecard = history.get_analyst_scorecard(
        lookback_days=config.get("history", {}).get("accuracy_lookback_days", 30)
    )
    if scorecard:
        logger.info("  Analyst scorecard:")
        for analyst, sc in scorecard.items():
            logger.info(f"    {analyst}: {sc['accuracy_pct']}% accuracy ({sc['total']} picks)")

    # Save today's recommendations
    history.save_recommendations(today, analyst_results, data.get("market_data", {}))

    # ── PHASE 4: Aggregation (accuracy-weighted) ──
    logger.info("\n📋 PHASE 4: Aggregating analyst opinions (weighted by accuracy + conviction)...")
    aggregated = aggregator.aggregate(analyst_results, market_briefing, scorecard=scorecard)
    consensus_buys = len(aggregated.get("consensus_buys", []))
    consensus_sells = len(aggregated.get("consensus_sells", []))
    logger.info(f"  Consensus buys: {consensus_buys}, sells: {consensus_sells}")

    # ── PHASE 5: Report Generation & Delivery ──
    logger.info("\n📧 PHASE 5: Generating and sending report...")
    html, text = email_sender.format_report(aggregated, analyst_results, scorecard)

    if save_report:
        paths = email_sender.save_to_file(html, text)
        logger.info(f"  Report saved: {paths[0]}")

    if not skip_email:
        sent = email_sender.send(html, text)
        if sent:
            logger.info("  Email sent successfully!")
        else:
            logger.warning("  Email sending failed. Check your email configuration.")
    else:
        logger.info("  Skipping email (--skip-email flag)")

    # Save full report to history
    full_report = {
        "date": today,
        "analyst_results": analyst_results,
        "aggregated": aggregated,
        "scorecard": scorecard,
    }
    history.save_report(today, full_report)

    # Summary
    elapsed = time.time() - start_time
    logger.info("\n" + "=" * 60)
    logger.info(f"Complete in {elapsed:.1f}s")
    logger.info(f"  Tickers analyzed: {len(watchlist)}")
    logger.info(f"  Analysts run: {len(analyst_results)}")
    logger.info(f"  Consensus buys: {consensus_buys}")
    logger.info(f"  Consensus sells: {consensus_sells}")
    logger.info("=" * 60)

    return full_report


def backtest(config_path: str = "config/settings.yaml",
             lookback_days: int = 90,
             starting_capital: float = 100_000,
             analyst_filter: list[str] | None = None):
    """Run a backtest over historical recommendations.

    Args:
        config_path: Path to the settings.yaml config file.
        lookback_days: How many days of history to test.
        starting_capital: Paper trading starting capital.
        analyst_filter: Only test these analysts (None = all).
    """
    load_dotenv()
    config = load_config(config_path)
    db_path = config.get("history", {}).get("db_path", "data/history.db")

    from .backtester import Backtester

    bt = Backtester(
        db_path=db_path,
        starting_capital=starting_capital,
    )

    logger.info("=" * 60)
    logger.info("SICA — Backtester")
    logger.info(f"Lookback: {lookback_days} days | Capital: ${starting_capital:,.0f}")
    if analyst_filter:
        logger.info(f"Analysts: {', '.join(analyst_filter)}")
    logger.info("=" * 60)

    results = bt.run(lookback_days=lookback_days, analyst_filter=analyst_filter)

    if "error" in results:
        logger.error(f"Backtest failed: {results['error']}")
        return results

    m = results["metrics"]
    logger.info("\n" + "=" * 60)
    logger.info("BACKTEST RESULTS")
    logger.info("=" * 60)
    logger.info(f"  Period: {m['period']['start']} to {m['period']['end']} ({m['period']['trading_days']} days)")
    logger.info(f"  Starting Capital:  ${m['starting_capital']:>12,.2f}")
    logger.info(f"  Ending Value:      ${m['ending_value']:>12,.2f}")
    logger.info(f"  Total Return:      {m['total_return_pct']:>11.2f}%")
    if m.get("benchmark_return_pct") is not None:
        logger.info(f"  SPY Benchmark:     {m['benchmark_return_pct']:>11.2f}%")
        logger.info(f"  Alpha:             {m['alpha']:>11.2f}%")
    logger.info(f"  Max Drawdown:      {m['max_drawdown_pct']:>11.2f}%")
    logger.info(f"  Sharpe Ratio:      {m['sharpe_ratio']:>11.2f}")
    logger.info(f"  Total Trades:      {m['total_trades']:>8d}")
    logger.info(f"  Win Rate:          {m['win_rate']:>11.1f}%")
    logger.info(f"  Avg Trade Return:  {m['avg_trade_return']:>11.2f}%")

    if m.get("best_trade"):
        logger.info(f"  Best Trade:        {m['best_trade']['ticker']} +{m['best_trade']['return_pct']}% ({m['best_trade']['analyst']})")
    if m.get("worst_trade"):
        logger.info(f"  Worst Trade:       {m['worst_trade']['ticker']} {m['worst_trade']['return_pct']}% ({m['worst_trade']['analyst']})")

    if m.get("analyst_breakdown"):
        logger.info("\n  Per-Analyst P&L:")
        for analyst, data in sorted(m["analyst_breakdown"].items(), key=lambda x: x[1]["pnl"], reverse=True):
            logger.info(f"    {analyst:20s}  ${data['pnl']:>10,.2f}  ({data['trades']} trades, {data['win_rate']}% win)")

    logger.info("=" * 60)

    # Save results to JSON
    import json
    os.makedirs("data", exist_ok=True)
    out_path = "data/backtest_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"Full results saved to {out_path}")

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="SICA — Sage Investor Council Agent",
        epilog="Analyst keys: warren_buffett, charlie_munger, george_soros, "
               "peter_lynch, ray_dalio, carl_icahn, benjamin_graham",
    )
    sub = parser.add_subparsers(dest="command")

    # Default: run the analysis pipeline
    run_parser = sub.add_parser("run", help="Run daily analysis (default)")
    run_parser.add_argument("--config", default="config/settings.yaml", help="Path to config file")
    run_parser.add_argument("--skip-email", action="store_true", help="Skip sending email")
    run_parser.add_argument("--no-save", action="store_true", help="Don't save report files")
    run_parser.add_argument(
        "--analysts", nargs="+", metavar="KEY", default=None,
        help="Run only these analysts",
    )

    # Backtest subcommand
    bt_parser = sub.add_parser("backtest", help="Backtest historical recommendations")
    bt_parser.add_argument("--config", default="config/settings.yaml", help="Path to config file")
    bt_parser.add_argument("--days", type=int, default=90, help="Lookback period in days (default: 90)")
    bt_parser.add_argument("--capital", type=float, default=100_000, help="Starting capital (default: 100000)")
    bt_parser.add_argument(
        "--analysts", nargs="+", metavar="NAME", default=None,
        help="Filter by analyst name (e.g. --analysts 'Warren Buffett' 'George Soros')",
    )

    # Also support running without subcommand (backwards compat)
    parser.add_argument("--config", default="config/settings.yaml", help="Path to config file")
    parser.add_argument("--skip-email", action="store_true", help="Skip sending email")
    parser.add_argument("--no-save", action="store_true", help="Don't save report files")
    parser.add_argument(
        "--analysts", nargs="+", metavar="KEY", default=None,
        help="Run only these analysts",
    )

    args = parser.parse_args()

    if args.command == "backtest":
        backtest(
            config_path=args.config,
            lookback_days=args.days,
            starting_capital=args.capital,
            analyst_filter=args.analysts,
        )
    else:
        main(
            config_path=args.config,
            skip_email=args.skip_email,
            save_report=not args.no_save,
            analysts_override=args.analysts,
        )
