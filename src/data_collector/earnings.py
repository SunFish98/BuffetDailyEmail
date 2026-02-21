"""Earnings report data collection."""

import os
import logging
from datetime import datetime, timedelta

import yfinance as yf
import requests

logger = logging.getLogger(__name__)


class EarningsCollector:
    """Collects earnings reports, estimates, and calendar data."""

    def __init__(self):
        self.finnhub_key = os.getenv("FINNHUB_API_KEY")

    def collect(self, tickers: list[str]) -> dict:
        """Collect earnings data for all tickers."""
        results = {}
        for ticker_symbol in tickers:
            try:
                results[ticker_symbol] = self._collect_yfinance(ticker_symbol)
                logger.info(f"Collected earnings data for {ticker_symbol}")
            except Exception as e:
                logger.warning(f"Failed earnings for {ticker_symbol}: {e}")
                results[ticker_symbol] = {"error": str(e)}

        # Upcoming earnings calendar
        results["_upcoming_earnings"] = self._upcoming_earnings_calendar()

        return results

    def _collect_yfinance(self, ticker_symbol: str) -> dict:
        """Get earnings data from yfinance."""
        ticker = yf.Ticker(ticker_symbol)

        # Historical earnings
        earnings_history = []
        try:
            earnings_df = ticker.earnings_history
            if earnings_df is not None and not earnings_df.empty:
                for _, row in earnings_df.iterrows():
                    earnings_history.append({
                        "date": str(row.get("Earnings Date", "")),
                        "eps_estimate": row.get("EPS Estimate"),
                        "eps_actual": row.get("Reported EPS"),
                        "surprise_pct": row.get("Surprise(%)"),
                    })
        except Exception:
            pass

        # Quarterly financials
        quarterly_earnings = []
        try:
            q_earnings = ticker.quarterly_earnings
            if q_earnings is not None and not q_earnings.empty:
                for date, row in q_earnings.iterrows():
                    quarterly_earnings.append({
                        "quarter": str(date),
                        "revenue": row.get("Revenue"),
                        "earnings": row.get("Earnings"),
                    })
        except Exception:
            pass

        # Next earnings date
        next_earnings = None
        try:
            calendar = ticker.calendar
            if calendar is not None:
                if isinstance(calendar, dict):
                    ed = calendar.get("Earnings Date")
                    if ed:
                        next_earnings = str(ed[0]) if isinstance(ed, list) else str(ed)
        except Exception:
            pass

        # Analyst recommendations
        recommendations = []
        try:
            recs = ticker.recommendations
            if recs is not None and not recs.empty:
                recent = recs.tail(5)
                for date, row in recent.iterrows():
                    recommendations.append({
                        "date": str(date),
                        "firm": row.get("Firm", ""),
                        "grade": row.get("To Grade", ""),
                        "action": row.get("Action", ""),
                    })
        except Exception:
            pass

        return {
            "earnings_history": earnings_history[-4:],  # Last 4 quarters
            "quarterly_earnings": quarterly_earnings[-4:],
            "next_earnings_date": next_earnings,
            "analyst_recommendations": recommendations,
        }

    def _upcoming_earnings_calendar(self) -> list[dict]:
        """Get upcoming earnings for the next week."""
        upcoming = []

        if self.finnhub_key:
            try:
                today = datetime.now().strftime("%Y-%m-%d")
                next_week = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
                resp = requests.get(
                    "https://finnhub.io/api/v1/calendar/earnings",
                    params={
                        "from": today,
                        "to": next_week,
                        "token": self.finnhub_key,
                    },
                    timeout=15,
                )
                data = resp.json()
                for item in data.get("earningsCalendar", [])[:20]:
                    upcoming.append({
                        "date": item.get("date"),
                        "ticker": item.get("symbol"),
                        "eps_estimate": item.get("epsEstimate"),
                        "revenue_estimate": item.get("revenueEstimate"),
                        "hour": item.get("hour", ""),  # bmo/amc
                    })
            except Exception as e:
                logger.warning(f"Failed upcoming earnings calendar: {e}")

        return upcoming
