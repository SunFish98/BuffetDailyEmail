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
from .analysts import ALL_ANALYSTS
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
         save_report: bool = True):
    """Main entry point for the daily analysis pipeline.

    Args:
        config_path: Path to the settings.yaml config file.
        skip_email: If True, skip sending the email (useful for testing).
        save_report: If True, save HTML/text reports to data/ directory.
    """
    load_dotenv()
    start_time = time.time()

    # Verify API key
    if not os.getenv("ANTHROPIC_API_KEY"):
        logger.error("ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("SICA — Sage Investor Council Agent")
    logger.info("=" * 60)

    # Load config
    config = load_config(config_path)
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

    if parallel:
        logger.info(f"Running {len(ALL_ANALYSTS)} analysts in parallel...")
        with ThreadPoolExecutor(max_workers=len(ALL_ANALYSTS)) as executor:
            futures = {
                executor.submit(run_analyst, cls, config, market_briefing): cls.name
                for cls in ALL_ANALYSTS
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
        for analyst_class in ALL_ANALYSTS:
            logger.info(f"  Running {analyst_class.name}...")
            result = run_analyst(analyst_class, config, market_briefing)
            analyst_results.append(result)
            picks = len(result.get("top_picks", []))
            logger.info(f"  ✓ {analyst_class.name}: {picks} picks")

    # ── PHASE 3: Aggregation ──
    logger.info("\n📋 PHASE 3: Aggregating analyst opinions...")
    aggregated = aggregator.aggregate(analyst_results, market_briefing)
    consensus_buys = len(aggregated.get("consensus_buys", []))
    consensus_sells = len(aggregated.get("consensus_sells", []))
    logger.info(f"  Consensus buys: {consensus_buys}, sells: {consensus_sells}")

    # ── PHASE 4: Historical Tracking ──
    logger.info("\n📈 PHASE 4: Updating historical records...")
    today = datetime.now().strftime("%Y-%m-%d")

    history.save_recommendations(today, analyst_results, data.get("market_data", {}))
    scorecard = history.get_analyst_scorecard(
        lookback_days=config.get("history", {}).get("accuracy_lookback_days", 30)
    )
    if scorecard:
        logger.info("  Analyst scorecard:")
        for analyst, sc in scorecard.items():
            logger.info(f"    {analyst}: {sc['accuracy_pct']}% accuracy ({sc['total']} picks)")

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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SICA — Sage Investor Council Agent")
    parser.add_argument("--config", default="config/settings.yaml", help="Path to config file")
    parser.add_argument("--skip-email", action="store_true", help="Skip sending email")
    parser.add_argument("--no-save", action="store_true", help="Don't save report files")
    args = parser.parse_args()

    main(config_path=args.config, skip_email=args.skip_email, save_report=not args.no_save)
