#!/usr/bin/env python3
"""Convenience entry point: python run.py [--skip-email] [--no-save]"""

import argparse
from src.main import main

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BuffetDailyEmail — Multi-Agent Stock Analysis")
    parser.add_argument("--config", default="config/settings.yaml", help="Path to config file")
    parser.add_argument("--skip-email", action="store_true", help="Skip sending email")
    parser.add_argument("--no-save", action="store_true", help="Don't save report files")
    args = parser.parse_args()

    main(config_path=args.config, skip_email=args.skip_email, save_report=not args.no_save)
