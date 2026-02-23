#!/usr/bin/env python3
"""SICA Web Interface — run with: python run_web.py"""

import argparse
from src.web import app

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SICA Web Interface")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    print(f"\n  SICA — Sage Investor Council Agent")
    print(f"  Web interface running at http://{args.host}:{args.port}\n")

    app.run(host=args.host, port=args.port, debug=args.debug)
