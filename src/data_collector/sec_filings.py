"""SEC EDGAR filing data collection."""

import os
import logging
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

# SEC EDGAR base URL
EDGAR_BASE = "https://efts.sec.gov/LATEST/search-index"
EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions"


class SECFilingsCollector:
    """Collects recent SEC filings from EDGAR."""

    def __init__(self):
        self.user_agent = os.getenv(
            "SEC_EDGAR_USER_AGENT",
            "SICA research@example.com"
        )
        self.headers = {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
        }

    def collect(self, tickers: list[str]) -> dict:
        """Collect recent SEC filings for all tickers."""
        results = {}
        for ticker in tickers:
            try:
                cik = self._get_cik(ticker)
                if cik:
                    filings = self._get_recent_filings(cik)
                    results[ticker] = {
                        "cik": cik,
                        "recent_filings": filings,
                    }
                else:
                    results[ticker] = {"error": "CIK not found"}
                logger.info(f"Collected SEC filings for {ticker}")
            except Exception as e:
                logger.warning(f"Failed SEC filings for {ticker}: {e}")
                results[ticker] = {"error": str(e)}

        return results

    def _get_cik(self, ticker: str) -> str | None:
        """Look up CIK number for a ticker."""
        try:
            resp = requests.get(
                "https://www.sec.gov/files/company_tickers.json",
                headers=self.headers,
                timeout=15,
            )
            data = resp.json()
            ticker_upper = ticker.upper().replace("-", ".")
            for entry in data.values():
                if entry.get("ticker", "").upper() == ticker_upper:
                    return str(entry["cik_str"]).zfill(10)
        except Exception as e:
            logger.warning(f"CIK lookup failed for {ticker}: {e}")
        return None

    def _get_recent_filings(self, cik: str, days: int = 30) -> list[dict]:
        """Get recent filings for a given CIK."""
        try:
            url = f"{EDGAR_SUBMISSIONS}/CIK{cik}.json"
            resp = requests.get(url, headers=self.headers, timeout=15)
            data = resp.json()

            recent = data.get("filings", {}).get("recent", {})
            if not recent:
                return []

            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

            filings = []
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            descriptions = recent.get("primaryDocDescription", [])
            accession_numbers = recent.get("accessionNumber", [])

            interesting_forms = {"10-K", "10-Q", "8-K", "4", "SC 13D", "SC 13G", "DEF 14A", "S-1"}

            for i in range(min(len(forms), len(dates))):
                if dates[i] < cutoff:
                    break
                if forms[i] in interesting_forms:
                    filings.append({
                        "form": forms[i],
                        "date": dates[i],
                        "description": descriptions[i] if i < len(descriptions) else "",
                        "accession": accession_numbers[i] if i < len(accession_numbers) else "",
                    })

            return filings[:10]  # Max 10 filings per ticker

        except Exception as e:
            logger.warning(f"Filing fetch failed for CIK {cik}: {e}")
            return []
