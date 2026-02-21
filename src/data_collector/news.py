"""Financial news collection from free and paid sources."""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional

import requests
import feedparser

logger = logging.getLogger(__name__)


class NewsCollector:
    """Collects financial news from multiple sources."""

    def __init__(self, sources: list[str] = None):
        self.sources = sources or ["google_rss"]
        self.finnhub_key = os.getenv("FINNHUB_API_KEY")
        self.newsapi_key = os.getenv("NEWSAPI_KEY")

    def collect(self, tickers: list[str], max_per_ticker: int = 5) -> dict:
        """Collect news for all tickers, trying sources in priority order."""
        results = {}
        for ticker in tickers:
            articles = []
            for source in self.sources:
                if articles:
                    break
                try:
                    if source == "google_rss":
                        articles = self._google_rss(ticker, max_per_ticker)
                    elif source == "finnhub" and self.finnhub_key:
                        articles = self._finnhub(ticker, max_per_ticker)
                    elif source == "newsapi" and self.newsapi_key:
                        articles = self._newsapi(ticker, max_per_ticker)
                except Exception as e:
                    logger.warning(f"News source {source} failed for {ticker}: {e}")
                    continue

            results[ticker] = articles
            logger.info(f"Collected {len(articles)} news articles for {ticker}")

        # Also collect general market news
        results["_market_general"] = self._general_market_news(max_per_ticker * 2)

        return results

    def _google_rss(self, ticker: str, max_articles: int) -> list[dict]:
        """Fetch news from Google News RSS (free, no API key)."""
        url = f"https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)

        articles = []
        for entry in feed.entries[:max_articles]:
            published = ""
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M")

            articles.append({
                "title": entry.get("title", ""),
                "source": entry.get("source", {}).get("title", "Unknown"),
                "published": published,
                "link": entry.get("link", ""),
                "summary": entry.get("summary", "")[:300],
            })

        return articles

    def _finnhub(self, ticker: str, max_articles: int) -> list[dict]:
        """Fetch news from Finnhub API."""
        today = datetime.now().strftime("%Y-%m-%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

        resp = requests.get(
            "https://finnhub.io/api/v1/company-news",
            params={
                "symbol": ticker,
                "from": week_ago,
                "to": today,
                "token": self.finnhub_key,
            },
            timeout=15,
        )
        data = resp.json()

        articles = []
        for item in data[:max_articles]:
            articles.append({
                "title": item.get("headline", ""),
                "source": item.get("source", "Unknown"),
                "published": datetime.fromtimestamp(item.get("datetime", 0)).strftime("%Y-%m-%d %H:%M"),
                "link": item.get("url", ""),
                "summary": (item.get("summary") or "")[:300],
            })

        return articles

    def _newsapi(self, ticker: str, max_articles: int) -> list[dict]:
        """Fetch news from NewsAPI."""
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": f"{ticker} stock",
                "sortBy": "publishedAt",
                "pageSize": max_articles,
                "language": "en",
                "apiKey": self.newsapi_key,
            },
            timeout=15,
        )
        data = resp.json()

        articles = []
        for item in data.get("articles", [])[:max_articles]:
            articles.append({
                "title": item.get("title", ""),
                "source": item.get("source", {}).get("name", "Unknown"),
                "published": (item.get("publishedAt") or "")[:16].replace("T", " "),
                "link": item.get("url", ""),
                "summary": (item.get("description") or "")[:300],
            })

        return articles

    def _general_market_news(self, max_articles: int) -> list[dict]:
        """Fetch general market/economy news."""
        queries = ["stock market today", "economy financial markets"]
        articles = []

        for query in queries:
            try:
                url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
                feed = feedparser.parse(url)
                for entry in feed.entries[:max_articles // 2]:
                    published = ""
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        published = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M")
                    articles.append({
                        "title": entry.get("title", ""),
                        "source": entry.get("source", {}).get("title", "Unknown"),
                        "published": published,
                        "link": entry.get("link", ""),
                        "summary": entry.get("summary", "")[:300],
                    })
            except Exception as e:
                logger.warning(f"Failed general market news for '{query}': {e}")

        return articles[:max_articles]
