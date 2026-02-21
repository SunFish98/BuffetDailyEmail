"""Historical tracking of recommendations using SQLite."""

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class HistoryTracker:
    """Tracks historical recommendations and their outcomes."""

    def __init__(self, db_path: str = "data/history.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize the database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS daily_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL UNIQUE,
                    report_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS recommendations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    analyst TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    action TEXT NOT NULL,
                    conviction TEXT,
                    reasoning TEXT,
                    price_at_recommendation REAL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS price_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    price REAL NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(date, ticker)
                );

                CREATE INDEX IF NOT EXISTS idx_rec_date ON recommendations(date);
                CREATE INDEX IF NOT EXISTS idx_rec_ticker ON recommendations(ticker);
                CREATE INDEX IF NOT EXISTS idx_rec_analyst ON recommendations(analyst);
                CREATE INDEX IF NOT EXISTS idx_price_ticker ON price_snapshots(ticker);
            """)

    def save_report(self, date: str, full_report: dict):
        """Save the full daily report."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO daily_reports (date, report_json) VALUES (?, ?)",
                (date, json.dumps(full_report, default=str)),
            )
        logger.info(f"Saved daily report for {date}")

    def save_recommendations(self, date: str, analyst_results: list[dict], market_data: dict):
        """Save individual recommendations and current prices."""
        with sqlite3.connect(self.db_path) as conn:
            for result in analyst_results:
                analyst_name = result.get("analyst", "Unknown")
                for pick in result.get("top_picks", []):
                    ticker = pick.get("ticker", "")
                    if not ticker:
                        continue

                    # Get current price
                    ticker_data = market_data.get(ticker, {})
                    price = ticker_data.get("current_price")

                    conn.execute(
                        """INSERT INTO recommendations
                           (date, analyst, ticker, action, conviction, reasoning, price_at_recommendation)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            date,
                            analyst_name,
                            ticker,
                            pick.get("action", "HOLD"),
                            pick.get("conviction", ""),
                            pick.get("reasoning", ""),
                            price,
                        ),
                    )

            # Save price snapshots
            for ticker, data in market_data.items():
                price = data.get("current_price")
                if price:
                    conn.execute(
                        "INSERT OR REPLACE INTO price_snapshots (date, ticker, price) VALUES (?, ?, ?)",
                        (date, ticker, price),
                    )

        logger.info(f"Saved recommendations for {date}")

    def get_accuracy_report(self, lookback_days: int = 30) -> list[dict]:
        """Calculate accuracy of past recommendations.

        Compares recommendation prices with current prices to see
        how well each analyst's picks have performed.
        """
        cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Get all recommendations within lookback period
            recs = conn.execute(
                """SELECT r.*, ps.price as current_price
                   FROM recommendations r
                   LEFT JOIN price_snapshots ps ON r.ticker = ps.ticker
                   AND ps.date = (SELECT MAX(date) FROM price_snapshots WHERE ticker = r.ticker)
                   WHERE r.date >= ?
                   ORDER BY r.analyst, r.date""",
                (cutoff,),
            ).fetchall()

        results = []
        for rec in recs:
            rec_price = rec["price_at_recommendation"]
            cur_price = rec["current_price"]

            if rec_price and cur_price and rec_price > 0:
                change_pct = (cur_price - rec_price) / rec_price * 100
                action = rec["action"]

                # A BUY is correct if price went up, SELL if price went down
                correct = (action == "BUY" and change_pct > 0) or (action == "SELL" and change_pct < 0)

                results.append({
                    "analyst": rec["analyst"],
                    "ticker": rec["ticker"],
                    "action": action,
                    "conviction": rec["conviction"],
                    "rec_date": rec["date"],
                    "rec_price": rec_price,
                    "current_price": cur_price,
                    "change_pct": round(change_pct, 2),
                    "correct": correct,
                })

        return results

    def get_analyst_scorecard(self, lookback_days: int = 30) -> dict:
        """Get a per-analyst accuracy scorecard."""
        accuracy_data = self.get_accuracy_report(lookback_days)

        scorecard = {}
        for rec in accuracy_data:
            analyst = rec["analyst"]
            if analyst not in scorecard:
                scorecard[analyst] = {
                    "total": 0,
                    "correct": 0,
                    "avg_return": 0,
                    "best_pick": None,
                    "worst_pick": None,
                }

            sc = scorecard[analyst]
            sc["total"] += 1
            if rec["correct"]:
                sc["correct"] += 1
            sc["avg_return"] = (
                (sc["avg_return"] * (sc["total"] - 1) + rec["change_pct"]) / sc["total"]
            )

            if sc["best_pick"] is None or rec["change_pct"] > sc["best_pick"]["change_pct"]:
                sc["best_pick"] = rec
            if sc["worst_pick"] is None or rec["change_pct"] < sc["worst_pick"]["change_pct"]:
                sc["worst_pick"] = rec

        # Calculate accuracy percentage
        for analyst, sc in scorecard.items():
            sc["accuracy_pct"] = round(sc["correct"] / sc["total"] * 100, 1) if sc["total"] > 0 else 0
            sc["avg_return"] = round(sc["avg_return"], 2)

        return scorecard

    def get_past_report(self, date: str) -> dict | None:
        """Retrieve a past daily report."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT report_json FROM daily_reports WHERE date = ?", (date,)
            ).fetchone()
            if row:
                return json.loads(row[0])
        return None
