"""Market data collection from free and paid sources."""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional

import yfinance as yf
import pandas as pd
import requests

logger = logging.getLogger(__name__)


class MarketDataCollector:
    """Collects stock price data, fundamentals, and key metrics."""

    def __init__(self, source: str = "yfinance"):
        self.source = source
        self.alpha_vantage_key = os.getenv("ALPHA_VANTAGE_API_KEY")
        self.polygon_key = os.getenv("POLYGON_API_KEY")

    def collect(self, tickers: list[str], history_days: int = 30) -> dict:
        """Collect market data for all tickers."""
        if self.source == "alpha_vantage" and self.alpha_vantage_key:
            return self._collect_alpha_vantage(tickers, history_days)
        elif self.source == "polygon" and self.polygon_key:
            return self._collect_polygon(tickers, history_days)
        else:
            return self._collect_yfinance(tickers, history_days)

    def _collect_yfinance(self, tickers: list[str], history_days: int) -> dict:
        """Collect data using yfinance (free)."""
        results = {}
        for ticker_symbol in tickers:
            try:
                ticker = yf.Ticker(ticker_symbol)
                info = ticker.info or {}

                # Price history
                hist = ticker.history(period=f"{history_days}d")
                price_history = []
                if not hist.empty:
                    for date, row in hist.iterrows():
                        price_history.append({
                            "date": date.strftime("%Y-%m-%d"),
                            "open": round(row.get("Open", 0), 2),
                            "high": round(row.get("High", 0), 2),
                            "low": round(row.get("Low", 0), 2),
                            "close": round(row.get("Close", 0), 2),
                            "volume": int(row.get("Volume", 0)),
                        })

                # Current price data
                current_price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
                prev_close = info.get("previousClose", 0)
                change_pct = ((current_price - prev_close) / prev_close * 100) if prev_close else 0

                # Fundamentals
                results[ticker_symbol] = {
                    "current_price": current_price,
                    "previous_close": prev_close,
                    "change_percent": round(change_pct, 2),
                    "market_cap": info.get("marketCap"),
                    "pe_ratio": info.get("trailingPE"),
                    "forward_pe": info.get("forwardPE"),
                    "peg_ratio": info.get("pegRatio"),
                    "price_to_book": info.get("priceToBook"),
                    "dividend_yield": info.get("dividendYield"),
                    "beta": info.get("beta"),
                    "52_week_high": info.get("fiftyTwoWeekHigh"),
                    "52_week_low": info.get("fiftyTwoWeekLow"),
                    "50_day_avg": info.get("fiftyDayAverage"),
                    "200_day_avg": info.get("twoHundredDayAverage"),
                    "avg_volume": info.get("averageVolume"),
                    # Financials
                    "revenue": info.get("totalRevenue"),
                    "net_income": info.get("netIncomeToCommon"),
                    "profit_margin": info.get("profitMargins"),
                    "operating_margin": info.get("operatingMargins"),
                    "roe": info.get("returnOnEquity"),
                    "roa": info.get("returnOnAssets"),
                    "debt_to_equity": info.get("debtToEquity"),
                    "current_ratio": info.get("currentRatio"),
                    "free_cash_flow": info.get("freeCashflow"),
                    "earnings_growth": info.get("earningsGrowth"),
                    "revenue_growth": info.get("revenueGrowth"),
                    "book_value": info.get("bookValue"),
                    # Meta
                    "sector": info.get("sector"),
                    "industry": info.get("industry"),
                    "company_name": info.get("shortName", ticker_symbol),
                    "description": info.get("longBusinessSummary", "")[:500],
                    # Price history
                    "price_history": price_history,
                }

                logger.info(f"Collected market data for {ticker_symbol}")
            except Exception as e:
                logger.warning(f"Failed to collect data for {ticker_symbol}: {e}")
                results[ticker_symbol] = {"error": str(e), "company_name": ticker_symbol}

        return results

    def _collect_alpha_vantage(self, tickers: list[str], history_days: int) -> dict:
        """Collect data using Alpha Vantage API."""
        results = {}
        base_url = "https://www.alphavantage.co/query"

        for ticker_symbol in tickers:
            try:
                # Daily prices
                params = {
                    "function": "TIME_SERIES_DAILY",
                    "symbol": ticker_symbol,
                    "outputsize": "compact",
                    "apikey": self.alpha_vantage_key,
                }
                resp = requests.get(base_url, params=params, timeout=15)
                data = resp.json()

                time_series = data.get("Time Series (Daily)", {})
                price_history = []
                for date_str, values in sorted(time_series.items(), reverse=True)[:history_days]:
                    price_history.append({
                        "date": date_str,
                        "open": float(values["1. open"]),
                        "high": float(values["2. high"]),
                        "low": float(values["3. low"]),
                        "close": float(values["4. close"]),
                        "volume": int(values["5. volume"]),
                    })

                # Company overview
                params = {
                    "function": "OVERVIEW",
                    "symbol": ticker_symbol,
                    "apikey": self.alpha_vantage_key,
                }
                resp = requests.get(base_url, params=params, timeout=15)
                overview = resp.json()

                current_price = price_history[0]["close"] if price_history else 0
                prev_close = price_history[1]["close"] if len(price_history) > 1 else 0
                change_pct = ((current_price - prev_close) / prev_close * 100) if prev_close else 0

                results[ticker_symbol] = {
                    "current_price": current_price,
                    "previous_close": prev_close,
                    "change_percent": round(change_pct, 2),
                    "market_cap": _safe_float(overview.get("MarketCapitalization")),
                    "pe_ratio": _safe_float(overview.get("TrailingPE")),
                    "forward_pe": _safe_float(overview.get("ForwardPE")),
                    "peg_ratio": _safe_float(overview.get("PEGRatio")),
                    "price_to_book": _safe_float(overview.get("PriceToBookRatio")),
                    "dividend_yield": _safe_float(overview.get("DividendYield")),
                    "beta": _safe_float(overview.get("Beta")),
                    "52_week_high": _safe_float(overview.get("52WeekHigh")),
                    "52_week_low": _safe_float(overview.get("52WeekLow")),
                    "50_day_avg": _safe_float(overview.get("50DayMovingAverage")),
                    "200_day_avg": _safe_float(overview.get("200DayMovingAverage")),
                    "profit_margin": _safe_float(overview.get("ProfitMargin")),
                    "operating_margin": _safe_float(overview.get("OperatingMarginTTM")),
                    "roe": _safe_float(overview.get("ReturnOnEquityTTM")),
                    "roa": _safe_float(overview.get("ReturnOnAssetsTTM")),
                    "debt_to_equity": _safe_float(overview.get("DebtToEquityRatio")),
                    "revenue": _safe_float(overview.get("RevenueTTM")),
                    "earnings_growth": _safe_float(overview.get("QuarterlyEarningsGrowthYOY")),
                    "revenue_growth": _safe_float(overview.get("QuarterlyRevenueGrowthYOY")),
                    "book_value": _safe_float(overview.get("BookValue")),
                    "sector": overview.get("Sector"),
                    "industry": overview.get("Industry"),
                    "company_name": overview.get("Name", ticker_symbol),
                    "description": (overview.get("Description") or "")[:500],
                    "price_history": price_history,
                }

                logger.info(f"Collected Alpha Vantage data for {ticker_symbol}")
            except Exception as e:
                logger.warning(f"Failed Alpha Vantage for {ticker_symbol}: {e}")
                results[ticker_symbol] = {"error": str(e), "company_name": ticker_symbol}

        return results

    def _collect_polygon(self, tickers: list[str], history_days: int) -> dict:
        """Collect data using Polygon.io API."""
        results = {}
        base_url = "https://api.polygon.io"
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=history_days)).strftime("%Y-%m-%d")

        for ticker_symbol in tickers:
            try:
                # Aggregates (bars)
                url = f"{base_url}/v2/aggs/ticker/{ticker_symbol}/range/1/day/{start_date}/{end_date}"
                resp = requests.get(url, params={"apiKey": self.polygon_key}, timeout=15)
                data = resp.json()

                price_history = []
                for bar in data.get("results", []):
                    bar_date = datetime.fromtimestamp(bar["t"] / 1000).strftime("%Y-%m-%d")
                    price_history.append({
                        "date": bar_date,
                        "open": bar["o"],
                        "high": bar["h"],
                        "low": bar["l"],
                        "close": bar["c"],
                        "volume": bar["v"],
                    })

                # Ticker details
                url = f"{base_url}/v3/reference/tickers/{ticker_symbol}"
                resp = requests.get(url, params={"apiKey": self.polygon_key}, timeout=15)
                details = resp.json().get("results", {})

                current_price = price_history[-1]["close"] if price_history else 0
                prev_close = price_history[-2]["close"] if len(price_history) > 1 else 0
                change_pct = ((current_price - prev_close) / prev_close * 100) if prev_close else 0

                results[ticker_symbol] = {
                    "current_price": current_price,
                    "previous_close": prev_close,
                    "change_percent": round(change_pct, 2),
                    "market_cap": details.get("market_cap"),
                    "sector": details.get("sic_description"),
                    "company_name": details.get("name", ticker_symbol),
                    "description": (details.get("description") or "")[:500],
                    "price_history": price_history,
                }

                logger.info(f"Collected Polygon data for {ticker_symbol}")
            except Exception as e:
                logger.warning(f"Failed Polygon for {ticker_symbol}: {e}")
                results[ticker_symbol] = {"error": str(e), "company_name": ticker_symbol}

        return results


def _safe_float(value) -> Optional[float]:
    """Safely convert a value to float."""
    if value is None or value == "None" or value == "-":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
