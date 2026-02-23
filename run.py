#!/usr/bin/env python3
"""SICA (Sage Investor Council Agent) — python run.py [--skip-email] [--no-save]"""

import argparse
from src.main import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SICA — Sage Investor Council Agent",
        epilog="Analyst keys: warren_buffett, charlie_munger, george_soros, "
               "peter_lynch, ray_dalio, carl_icahn, benjamin_graham",
    )
    parser.add_argument("--config", default="config/settings.yaml", help="Path to config file")
    parser.add_argument("--skip-email", action="store_true", help="Skip sending email")
    parser.add_argument("--no-save", action="store_true", help="Don't save report files")
    parser.add_argument(
        "--analysts", nargs="+", metavar="KEY", default=None,
        help="Run only these analysts (e.g. --analysts warren_buffett benjamin_graham)",
    )
    args = parser.parse_args()

    main(
        config_path=args.config,
        skip_email=args.skip_email,
        save_report=not args.no_save,
        analysts_override=args.analysts,
    )
