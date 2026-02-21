"""Main data collection orchestrator."""

import logging
from datetime import datetime

from .market_data import MarketDataCollector
from .news import NewsCollector
from .earnings import EarningsCollector
from .macro import MacroCollector
from .sec_filings import SECFilingsCollector
from .insider import InsiderTradingCollector

logger = logging.getLogger(__name__)


class DataCollector:
    """Orchestrates all data collection modules."""

    def __init__(self, config: dict):
        dc_config = config.get("data_collection", {})

        self.market_data = MarketDataCollector(
            source=dc_config.get("market_data_source", "yfinance")
        )
        self.news = NewsCollector(
            sources=dc_config.get("news_sources", ["google_rss"])
        )
        self.earnings = EarningsCollector()
        self.macro = MacroCollector()
        self.sec_filings = SECFilingsCollector()
        self.insider = InsiderTradingCollector()

        self.history_days = dc_config.get("price_history_days", 30)
        self.max_news = dc_config.get("max_news_per_ticker", 5)
        self.enable_sec = dc_config.get("enable_sec_filings", True)
        self.enable_insider = dc_config.get("enable_insider_trading", True)
        self.enable_macro = dc_config.get("enable_macro_indicators", True)
        self.enable_earnings = dc_config.get("enable_earnings", True)

    def collect_all(self, tickers: list[str]) -> dict:
        """Collect all data for the given watchlist.

        Returns a structured dict with all collected data ready for analyst agents.
        """
        logger.info(f"Starting data collection for {len(tickers)} tickers")
        collection_start = datetime.now()

        result = {
            "metadata": {
                "collection_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "ticker_count": len(tickers),
                "tickers": tickers,
            },
            "market_data": {},
            "news": {},
            "earnings": {},
            "macro": {},
            "sec_filings": {},
            "insider_trading": {},
        }

        # Market data (always collected)
        logger.info("Collecting market data...")
        result["market_data"] = self.market_data.collect(tickers, self.history_days)

        # News
        logger.info("Collecting news...")
        result["news"] = self.news.collect(tickers, self.max_news)

        # Earnings
        if self.enable_earnings:
            logger.info("Collecting earnings data...")
            result["earnings"] = self.earnings.collect(tickers)

        # Macro indicators
        if self.enable_macro:
            logger.info("Collecting macro indicators...")
            result["macro"] = self.macro.collect()

        # SEC filings
        if self.enable_sec:
            logger.info("Collecting SEC filings...")
            result["sec_filings"] = self.sec_filings.collect(tickers)

        # Insider trading
        if self.enable_insider:
            logger.info("Collecting insider trading data...")
            result["insider_trading"] = self.insider.collect(tickers)

        elapsed = (datetime.now() - collection_start).total_seconds()
        result["metadata"]["collection_time_seconds"] = round(elapsed, 1)
        logger.info(f"Data collection complete in {elapsed:.1f}s")

        return result

    def prepare_analyst_context(self, data: dict, ticker: str) -> dict:
        """Extract and format data for a single ticker for analyst consumption.

        This creates a focused data package for a specific stock that
        analyst agents can reason about.
        """
        return {
            "ticker": ticker,
            "market_data": data["market_data"].get(ticker, {}),
            "news": data["news"].get(ticker, []),
            "earnings": data["earnings"].get(ticker, {}),
            "insider_trading": data["insider_trading"].get(ticker, {}),
            "sec_filings": data["sec_filings"].get(ticker, {}),
            "macro_environment": data.get("macro", {}),
            "general_market_news": data["news"].get("_market_general", []),
        }

    def prepare_full_context(self, data: dict) -> str:
        """Prepare a text summary of all collected data for analyst consumption.

        This creates a comprehensive text briefing that analyst agents
        can analyze holistically across all tickers.
        """
        lines = []
        lines.append(f"=== MARKET DATA BRIEFING ({data['metadata']['collection_date']}) ===\n")

        # Macro overview
        macro = data.get("macro", {})
        macro_summary = macro.get("macro_summary", "")
        if macro_summary:
            lines.append(f"MACRO ENVIRONMENT: {macro_summary}\n")

        # General market news
        general_news = data.get("news", {}).get("_market_general", [])
        if general_news:
            lines.append("MARKET NEWS:")
            for article in general_news[:5]:
                lines.append(f"  - [{article.get('source', '')}] {article.get('title', '')}")
            lines.append("")

        # Per-ticker data
        for ticker in data["metadata"]["tickers"]:
            md = data["market_data"].get(ticker, {})
            if md.get("error"):
                lines.append(f"\n--- {ticker}: Data unavailable ({md['error']}) ---")
                continue

            name = md.get("company_name", ticker)
            price = md.get("current_price", "N/A")
            change = md.get("change_percent", 0)
            change_str = f"+{change}%" if change >= 0 else f"{change}%"

            lines.append(f"\n--- {ticker} ({name}) | ${price} ({change_str}) ---")

            # Key metrics
            metrics = []
            if md.get("pe_ratio"):
                metrics.append(f"P/E: {md['pe_ratio']:.1f}")
            if md.get("forward_pe"):
                metrics.append(f"Fwd P/E: {md['forward_pe']:.1f}")
            if md.get("peg_ratio"):
                metrics.append(f"PEG: {md['peg_ratio']:.2f}")
            if md.get("price_to_book"):
                metrics.append(f"P/B: {md['price_to_book']:.2f}")
            if md.get("dividend_yield"):
                metrics.append(f"Div: {md['dividend_yield']:.2%}")
            if md.get("roe"):
                metrics.append(f"ROE: {md['roe']:.2%}")
            if md.get("debt_to_equity"):
                metrics.append(f"D/E: {md['debt_to_equity']:.1f}")
            if md.get("current_ratio"):
                metrics.append(f"Current: {md['current_ratio']:.2f}")
            if md.get("profit_margin"):
                metrics.append(f"Margin: {md['profit_margin']:.2%}")
            if md.get("free_cash_flow"):
                fcf_b = md['free_cash_flow'] / 1e9
                metrics.append(f"FCF: ${fcf_b:.1f}B")
            if md.get("market_cap"):
                cap_b = md['market_cap'] / 1e9
                metrics.append(f"MCap: ${cap_b:.0f}B")

            if metrics:
                lines.append(f"  Metrics: {' | '.join(metrics)}")

            # 52-week range context
            if md.get("52_week_high") and md.get("52_week_low"):
                high = md["52_week_high"]
                low = md["52_week_low"]
                if high > low:
                    position = (price - low) / (high - low) * 100 if isinstance(price, (int, float)) else 0
                    lines.append(f"  52W Range: ${low:.2f} - ${high:.2f} (at {position:.0f}%)")

            # News
            ticker_news = data.get("news", {}).get(ticker, [])
            if ticker_news:
                lines.append(f"  News:")
                for article in ticker_news[:3]:
                    lines.append(f"    - {article.get('title', '')}")

            # Earnings
            earnings = data.get("earnings", {}).get(ticker, {})
            if earnings.get("next_earnings_date"):
                lines.append(f"  Next Earnings: {earnings['next_earnings_date']}")
            recent_earnings = earnings.get("earnings_history", [])
            if recent_earnings:
                last = recent_earnings[-1]
                surprise = last.get("surprise_pct")
                if surprise is not None:
                    lines.append(f"  Last Earnings Surprise: {surprise:+.1f}%")

            # Insider trading
            insider = data.get("insider_trading", {}).get(ticker, {})
            sentiment = insider.get("insider_sentiment")
            if sentiment and sentiment != "neutral":
                lines.append(f"  Insider Sentiment: {sentiment}")

            # SEC filings
            filings = data.get("sec_filings", {}).get(ticker, {}).get("recent_filings", [])
            important_filings = [f for f in filings if f.get("form") in ("10-K", "10-Q", "8-K")]
            if important_filings:
                lines.append(f"  Recent Filings:")
                for f in important_filings[:3]:
                    lines.append(f"    - {f['form']} ({f['date']}): {f.get('description', '')}")

        return "\n".join(lines)
