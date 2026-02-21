"""Insider trading activity collection."""

import os
import logging
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)


class InsiderTradingCollector:
    """Collects insider trading data from Finnhub or SEC Form 4 filings."""

    def __init__(self):
        self.finnhub_key = os.getenv("FINNHUB_API_KEY")

    def collect(self, tickers: list[str]) -> dict:
        """Collect insider trading activity for all tickers."""
        results = {}
        for ticker in tickers:
            try:
                if self.finnhub_key:
                    results[ticker] = self._finnhub_insider(ticker)
                else:
                    results[ticker] = self._sec_form4(ticker)
                logger.info(f"Collected insider trading for {ticker}")
            except Exception as e:
                logger.warning(f"Failed insider trading for {ticker}: {e}")
                results[ticker] = {"transactions": [], "error": str(e)}

        return results

    def _finnhub_insider(self, ticker: str) -> dict:
        """Get insider transactions from Finnhub."""
        resp = requests.get(
            "https://finnhub.io/api/v1/stock/insider-transactions",
            params={"symbol": ticker, "token": self.finnhub_key},
            timeout=15,
        )
        data = resp.json()

        transactions = []
        total_bought = 0
        total_sold = 0

        for tx in data.get("data", [])[:15]:
            change = tx.get("change", 0) or 0
            price = tx.get("transactionPrice", 0) or 0
            tx_type = "buy" if change > 0 else "sell"
            value = abs(change * price)

            if tx_type == "buy":
                total_bought += value
            else:
                total_sold += value

            transactions.append({
                "name": tx.get("name", "Unknown"),
                "title": tx.get("filingDate", ""),
                "date": tx.get("transactionDate", ""),
                "type": tx_type,
                "shares": abs(change),
                "price": price,
                "value": round(value, 2),
            })

        sentiment = "neutral"
        if total_bought > total_sold * 2:
            sentiment = "strongly bullish"
        elif total_bought > total_sold:
            sentiment = "bullish"
        elif total_sold > total_bought * 2:
            sentiment = "strongly bearish"
        elif total_sold > total_bought:
            sentiment = "bearish"

        return {
            "transactions": transactions,
            "total_bought_value": round(total_bought, 2),
            "total_sold_value": round(total_sold, 2),
            "insider_sentiment": sentiment,
        }

    def _sec_form4(self, ticker: str) -> dict:
        """Fallback: get insider data from SEC EDGAR Form 4 filings."""
        # SEC EDGAR full-text search for Form 4 filings
        user_agent = os.getenv(
            "SEC_EDGAR_USER_AGENT",
            "BuffetDailyEmail research@example.com"
        )
        try:
            resp = requests.get(
                "https://efts.sec.gov/LATEST/search-index",
                params={
                    "q": f'"{ticker}"',
                    "dateRange": "custom",
                    "startdt": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
                    "enddt": datetime.now().strftime("%Y-%m-%d"),
                    "forms": "4",
                },
                headers={"User-Agent": user_agent},
                timeout=15,
            )
            data = resp.json()
            hits = data.get("hits", {}).get("hits", [])

            transactions = []
            for hit in hits[:10]:
                source = hit.get("_source", {})
                transactions.append({
                    "date": source.get("file_date", ""),
                    "form": "4",
                    "entity": source.get("entity_name", ""),
                })

            return {
                "transactions": transactions,
                "note": "Basic Form 4 data. Set FINNHUB_API_KEY for detailed insider trading data.",
            }
        except Exception as e:
            return {
                "transactions": [],
                "note": f"SEC Form 4 lookup failed: {e}. Set FINNHUB_API_KEY for insider data.",
            }
