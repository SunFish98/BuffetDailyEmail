"""Backtester — replays historical recommendations against real price data.

Uses yfinance to fetch actual historical prices and simulates what would
have happened if you followed the analyst recommendations.
"""

import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

try:
    import yfinance as yf
except ImportError:
    yf = None
    logger.warning("yfinance not installed — backtester requires it: pip install yfinance")

from .paper_trader import PaperTrader


def _fetch_prices(tickers: list[str], start: str, end: str) -> dict:
    """Fetch daily close prices for tickers from yfinance.

    Returns:
        {ticker: {date_str: close_price, ...}, ...}
    """
    if not yf:
        raise ImportError("yfinance is required for backtesting: pip install yfinance")

    if not tickers:
        return {}

    logger.info(f"Fetching price history for {len(tickers)} tickers ({start} to {end})...")

    # yfinance can download multiple tickers at once
    raw = yf.download(
        tickers, start=start, end=end,
        progress=False, auto_adjust=True, threads=True,
    )

    prices = {}
    if len(tickers) == 1:
        # Single ticker: raw["Close"] is a Series
        ticker = tickers[0]
        prices[ticker] = {}
        close = raw["Close"]
        for dt, price in close.items():
            if price and price > 0:
                prices[ticker][dt.strftime("%Y-%m-%d")] = float(price)
    else:
        # Multiple tickers: raw["Close"] is a DataFrame with ticker columns
        close_df = raw["Close"]
        for ticker in tickers:
            prices[ticker] = {}
            if ticker in close_df.columns:
                for dt, price in close_df[ticker].items():
                    if price and price > 0:
                        prices[ticker][dt.strftime("%Y-%m-%d")] = float(price)

    logger.info(f"Fetched prices for {len(prices)} tickers")
    return prices


def _get_trading_dates(start: str, end: str, price_data: dict) -> list[str]:
    """Extract sorted list of trading dates from price data."""
    all_dates = set()
    for ticker_prices in price_data.values():
        all_dates.update(ticker_prices.keys())
    dates = sorted(d for d in all_dates if start <= d <= end)
    return dates


class Backtester:
    """Replays analyst recommendations from the history database.

    Can operate in two modes:
    1. **DB mode**: Replay recommendations stored in HistoryTracker's SQLite DB.
    2. **Direct mode**: Accept a list of recommendation dicts directly (for testing).
    """

    # Map analyst names to horizons
    ANALYST_HORIZONS = {
        "Warren Buffett": "long",
        "Charlie Munger": "long",
        "Benjamin Graham": "long",
        "Peter Lynch": "medium",
        "Ray Dalio": "medium",
        "Carl Icahn": "medium",
        "George Soros": "short",
        "Nassim Taleb": "short",
    }

    HOLD_DAYS = {"short": 20, "medium": 60, "long": 120}

    def __init__(self, db_path: str = "data/history.db",
                 starting_capital: float = 100_000,
                 stop_loss_pct: float = 0.15):
        self.db_path = db_path
        self.starting_capital = starting_capital
        self.stop_loss_pct = stop_loss_pct

    def _load_recommendations(self, start_date: str, end_date: str,
                              analyst_filter: list[str] | None = None) -> list[dict]:
        """Load recommendations from SQLite history DB."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            query = """
                SELECT date, analyst, ticker, action, conviction,
                       reasoning, price_at_recommendation
                FROM recommendations
                WHERE date >= ? AND date <= ?
                  AND action IN ('BUY', 'SELL')
            """
            params = [start_date, end_date]

            if analyst_filter:
                placeholders = ",".join("?" * len(analyst_filter))
                query += f" AND analyst IN ({placeholders})"
                params.extend(analyst_filter)

            query += " ORDER BY date, analyst"
            rows = conn.execute(query, params).fetchall()

        recs = [dict(r) for r in rows]
        logger.info(
            f"Loaded {len(recs)} recommendations from {start_date} to {end_date}"
        )
        return recs

    def run(self, lookback_days: int = 90,
            analyst_filter: list[str] | None = None,
            start_date: str | None = None,
            end_date: str | None = None) -> dict:
        """Run a backtest over historical recommendations.

        Args:
            lookback_days: How many days back to test (ignored if start_date set).
            analyst_filter: Only test these analysts (None = all).
            start_date: Explicit start date (YYYY-MM-DD).
            end_date: Explicit end date (YYYY-MM-DD).

        Returns:
            Full backtest results dict.
        """
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            start_dt = datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=lookback_days)
            start_date = start_dt.strftime("%Y-%m-%d")

        # Load recommendations
        recs = self._load_recommendations(start_date, end_date, analyst_filter)
        if not recs:
            return {
                "error": "No recommendations found in the specified period.",
                "period": {"start": start_date, "end": end_date},
            }

        # Collect all tickers mentioned
        all_tickers = list({r["ticker"] for r in recs})
        # Also fetch SPY as benchmark
        if "SPY" not in all_tickers:
            all_tickers.append("SPY")

        # Fetch real price data
        # Extend end date by max hold period to cover exits
        fetch_end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=150)
        fetch_end = fetch_end_dt.strftime("%Y-%m-%d")
        price_data = _fetch_prices(all_tickers, start_date, fetch_end)

        if not price_data:
            return {
                "error": "Could not fetch price data. Check your internet connection.",
                "period": {"start": start_date, "end": end_date},
            }

        trading_dates = _get_trading_dates(start_date, fetch_end, price_data)
        if not trading_dates:
            return {
                "error": "No trading dates found in price data.",
                "period": {"start": start_date, "end": end_date},
            }

        # Build hold-days map per analyst
        hold_days_map = {}
        for analyst, horizon in self.ANALYST_HORIZONS.items():
            hold_days_map[analyst] = self.HOLD_DAYS[horizon]

        # Group recommendations by date
        recs_by_date = defaultdict(list)
        for r in recs:
            recs_by_date[r["date"]].append(r)

        # Initialize paper trader
        trader = PaperTrader(
            starting_capital=self.starting_capital,
            stop_loss_pct=self.stop_loss_pct,
        )

        # Replay day by day
        for date in trading_dates:
            # Current prices for today
            current_prices = {}
            for ticker, tp in price_data.items():
                if date in tp:
                    current_prices[ticker] = tp[date]

            if not current_prices:
                continue

            # Check exits first (stop-loss, hold period expiry)
            trader.check_exits(date, current_prices, hold_days_map)

            # Process new recommendations for this date
            for rec in recs_by_date.get(date, []):
                ticker = rec["ticker"]
                price = current_prices.get(ticker)
                if not price:
                    # Try rec's stored price as fallback
                    price = rec.get("price_at_recommendation")
                if not price or price <= 0:
                    continue

                direction = "long" if rec["action"] == "BUY" else "short"
                trader.open_position(
                    ticker=ticker, direction=direction,
                    price=price, date=date,
                    analyst=rec["analyst"],
                    conviction=rec.get("conviction", "MEDIUM"),
                    current_prices=current_prices,
                )

            # Daily snapshot
            trader.take_snapshot(date, current_prices)

        # Close any remaining positions at last available prices
        last_date = trading_dates[-1]
        last_prices = {}
        for ticker, tp in price_data.items():
            if last_date in tp:
                last_prices[ticker] = tp[last_date]

        for p in list(trader.positions):
            price = last_prices.get(p.ticker, p.entry_price)
            trader.close_position(p, price, last_date)
            trader.take_snapshot(last_date, last_prices)

        # Benchmark: SPY buy-and-hold
        spy_prices = price_data.get("SPY", {})
        spy_start = spy_prices.get(trading_dates[0])
        spy_end = spy_prices.get(trading_dates[-1])
        if spy_start and spy_end and spy_start > 0:
            benchmark_return = (spy_end - spy_start) / spy_start * 100
        else:
            benchmark_return = None

        metrics = trader.get_metrics()
        metrics["benchmark_return_pct"] = round(benchmark_return, 2) if benchmark_return else None
        if benchmark_return is not None:
            metrics["alpha"] = round(metrics["total_return_pct"] - benchmark_return, 2)
        else:
            metrics["alpha"] = None

        return {
            "metrics": metrics,
            "equity_curve": trader.get_equity_curve(),
            "trades": [
                {
                    "ticker": t.ticker, "direction": t.direction,
                    "entry_date": t.entry_date, "exit_date": t.exit_date,
                    "entry_price": round(t.entry_price, 2),
                    "exit_price": round(t.exit_price, 2),
                    "return_pct": round(t.return_pct, 2),
                    "pnl": round(t.pnl, 2),
                    "analyst": t.analyst, "conviction": t.conviction,
                }
                for t in trader.closed_trades
            ],
            "trade_log": trader.trade_log,
            "recommendations_tested": len(recs),
            "tickers_traded": len(all_tickers),
        }

    def run_direct(self, recommendations: list[dict],
                   start_date: str, end_date: str) -> dict:
        """Run backtest with directly provided recommendations (no DB).

        Args:
            recommendations: List of dicts with keys:
                date, analyst, ticker, action, conviction
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).

        Returns:
            Full backtest results dict (same format as run()).
        """
        # Collect tickers
        all_tickers = list({r["ticker"] for r in recommendations})
        if "SPY" not in all_tickers:
            all_tickers.append("SPY")

        fetch_end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=150)
        fetch_end = fetch_end_dt.strftime("%Y-%m-%d")
        price_data = _fetch_prices(all_tickers, start_date, fetch_end)

        trading_dates = _get_trading_dates(start_date, fetch_end, price_data)
        if not trading_dates:
            return {"error": "No trading dates found."}

        hold_days_map = {}
        for analyst, horizon in self.ANALYST_HORIZONS.items():
            hold_days_map[analyst] = self.HOLD_DAYS[horizon]

        recs_by_date = defaultdict(list)
        for r in recommendations:
            recs_by_date[r["date"]].append(r)

        trader = PaperTrader(
            starting_capital=self.starting_capital,
            stop_loss_pct=self.stop_loss_pct,
        )

        for date in trading_dates:
            current_prices = {
                t: tp[date] for t, tp in price_data.items() if date in tp
            }
            if not current_prices:
                continue

            trader.check_exits(date, current_prices, hold_days_map)

            for rec in recs_by_date.get(date, []):
                ticker = rec["ticker"]
                price = current_prices.get(ticker)
                if not price or price <= 0:
                    continue
                direction = "long" if rec["action"] == "BUY" else "short"
                trader.open_position(
                    ticker=ticker, direction=direction,
                    price=price, date=date,
                    analyst=rec["analyst"],
                    conviction=rec.get("conviction", "MEDIUM"),
                    current_prices=current_prices,
                )

            trader.take_snapshot(date, current_prices)

        # Close remaining
        last_date = trading_dates[-1]
        last_prices = {t: tp[last_date] for t, tp in price_data.items() if last_date in tp}
        for p in list(trader.positions):
            trader.close_position(p, last_prices.get(p.ticker, p.entry_price), last_date)

        spy_prices = price_data.get("SPY", {})
        spy_start = spy_prices.get(trading_dates[0])
        spy_end = spy_prices.get(trading_dates[-1])
        benchmark_return = ((spy_end - spy_start) / spy_start * 100) if spy_start and spy_end and spy_start > 0 else None

        metrics = trader.get_metrics()
        metrics["benchmark_return_pct"] = round(benchmark_return, 2) if benchmark_return else None
        metrics["alpha"] = round(metrics["total_return_pct"] - benchmark_return, 2) if benchmark_return else None

        return {
            "metrics": metrics,
            "equity_curve": trader.get_equity_curve(),
            "trades": [
                {
                    "ticker": t.ticker, "direction": t.direction,
                    "entry_date": t.entry_date, "exit_date": t.exit_date,
                    "entry_price": round(t.entry_price, 2),
                    "exit_price": round(t.exit_price, 2),
                    "return_pct": round(t.return_pct, 2),
                    "pnl": round(t.pnl, 2),
                    "analyst": t.analyst, "conviction": t.conviction,
                }
                for t in trader.closed_trades
            ],
            "recommendations_tested": len(recommendations),
        }
