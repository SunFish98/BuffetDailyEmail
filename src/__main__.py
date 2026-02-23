"""Allow running as: python -m src"""

from .main import main

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SICA — Sage Investor Council Agent")
    parser.add_argument("--config", default="config/settings.yaml", help="Path to config file")
    parser.add_argument("--skip-email", action="store_true", help="Skip sending email")
    parser.add_argument("--no-save", action="store_true", help="Don't save report files")
    args = parser.parse_args()

    main(config_path=args.config, skip_email=args.skip_email, save_report=not args.no_save)
