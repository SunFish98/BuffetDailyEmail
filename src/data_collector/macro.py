"""Macroeconomic indicator collection from FRED and other sources."""

import os
import logging
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

# Key FRED series IDs for macro analysis
FRED_SERIES = {
    "fed_funds_rate": "FEDFUNDS",
    "10yr_treasury": "DGS10",
    "2yr_treasury": "DGS2",
    "yield_curve_spread": "T10Y2Y",
    "cpi_yoy": "CPIAUCSL",
    "core_cpi": "CPILFESL",
    "unemployment_rate": "UNRATE",
    "gdp_growth": "A191RL1Q225SBEA",
    "consumer_sentiment": "UMCSENT",
    "vix": "VIXCLS",
    "sp500": "SP500",
    "housing_starts": "HOUST",
    "industrial_production": "INDPRO",
    "retail_sales": "RSAFS",
    "money_supply_m2": "M2SL",
}


class MacroCollector:
    """Collects macroeconomic indicators from FRED API."""

    def __init__(self):
        self.fred_key = os.getenv("FRED_API_KEY")
        self.base_url = "https://api.stlouisfed.org/fred"

    def collect(self) -> dict:
        """Collect all macro indicators."""
        if not self.fred_key:
            logger.warning("FRED_API_KEY not set, skipping macro data")
            return self._fallback_macro_data()

        results = {}
        for name, series_id in FRED_SERIES.items():
            try:
                value, date = self._get_latest(series_id)
                results[name] = {
                    "value": value,
                    "date": date,
                    "series_id": series_id,
                }
            except Exception as e:
                logger.warning(f"Failed FRED series {name} ({series_id}): {e}")
                results[name] = {"value": None, "error": str(e)}

        # Add derived indicators
        results["yield_curve_inverted"] = self._is_yield_curve_inverted(results)
        results["macro_summary"] = self._generate_summary(results)

        return results

    def _get_latest(self, series_id: str) -> tuple:
        """Get the latest value for a FRED series."""
        resp = requests.get(
            f"{self.base_url}/series/observations",
            params={
                "series_id": series_id,
                "api_key": self.fred_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 5,
            },
            timeout=15,
        )
        data = resp.json()
        observations = data.get("observations", [])

        # Find first non-missing value
        for obs in observations:
            if obs.get("value") and obs["value"] != ".":
                return float(obs["value"]), obs["date"]

        return None, None

    def _is_yield_curve_inverted(self, results: dict) -> dict:
        """Check if yield curve is inverted (recession signal)."""
        spread = results.get("yield_curve_spread", {}).get("value")
        if spread is not None:
            return {
                "inverted": spread < 0,
                "spread": spread,
                "signal": "Recession warning" if spread < 0 else "Normal",
            }
        return {"inverted": None, "signal": "Data unavailable"}

    def _generate_summary(self, results: dict) -> str:
        """Generate a human-readable macro summary."""
        parts = []

        fed_rate = results.get("fed_funds_rate", {}).get("value")
        if fed_rate is not None:
            parts.append(f"Fed Funds Rate: {fed_rate}%")

        unemployment = results.get("unemployment_rate", {}).get("value")
        if unemployment is not None:
            parts.append(f"Unemployment: {unemployment}%")

        vix = results.get("vix", {}).get("value")
        if vix is not None:
            fear = "elevated fear" if vix > 25 else "moderate" if vix > 18 else "low volatility"
            parts.append(f"VIX: {vix} ({fear})")

        yc = results.get("yield_curve_inverted", {})
        if yc.get("inverted") is not None:
            parts.append(f"Yield Curve: {yc['signal']} (spread: {yc.get('spread')})")

        gdp = results.get("gdp_growth", {}).get("value")
        if gdp is not None:
            parts.append(f"GDP Growth: {gdp}%")

        return "; ".join(parts) if parts else "Macro data unavailable"

    def _fallback_macro_data(self) -> dict:
        """Minimal macro data when FRED key is not available."""
        return {
            "macro_summary": "FRED API key not configured. Set FRED_API_KEY in .env for macro data.",
            "note": "Sign up for free at https://fred.stlouisfed.org/docs/api/api_key.html",
        }
