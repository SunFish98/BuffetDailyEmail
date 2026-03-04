"""Aggregator agent — synthesizes all analyst opinions into a final report."""

import json
import logging
import os
from collections import defaultdict

from ..llm_client import LLMClient

logger = logging.getLogger(__name__)


class Aggregator:
    """Aggregates all analyst outputs into a final investment intelligence report."""

    def __init__(self, config: dict):
        self.config = config
        agg_config = config.get("aggregator", {})
        self.consensus_threshold = agg_config.get("consensus_threshold", 3)
        self.weights = agg_config.get("weights", {})
        self.llm = LLMClient(config)

    def aggregate(self, analyst_results: list[dict], market_briefing: str) -> dict:
        """Aggregate all analyst results into a final report.

        Args:
            analyst_results: List of dicts from each analyst's analyze() call.
            market_briefing: The original market data briefing text.

        Returns:
            Final aggregated report dict.
        """
        logger.info(f"Aggregating results from {len(analyst_results)} analysts")

        # Step 1: Mechanical aggregation (find consensus/disagreements)
        mechanical = self._mechanical_aggregation(analyst_results)

        # Step 2: LLM synthesis for narrative and final recommendations
        synthesis = self._llm_synthesis(analyst_results, mechanical, market_briefing)

        return {
            "consensus_buys": mechanical["consensus_buys"],
            "consensus_sells": mechanical["consensus_sells"],
            "disagreements": mechanical["disagreements"],
            "all_picks": mechanical["all_picks"],
            "synthesis": synthesis,
            "analyst_summaries": [
                {
                    "analyst": r.get("analyst", "Unknown"),
                    "market_outlook": r.get("market_outlook", ""),
                    "pick_count": len(r.get("top_picks", [])),
                    "avoid_count": len(r.get("avoid_list", [])),
                }
                for r in analyst_results
            ],
        }

    def _mechanical_aggregation(self, analyst_results: list[dict]) -> dict:
        """Find consensus and disagreements across analysts."""
        # Track all opinions per ticker
        ticker_opinions = defaultdict(list)

        for result in analyst_results:
            analyst_name = result.get("analyst", "Unknown")

            for pick in result.get("top_picks", []):
                ticker = pick.get("ticker", "")
                if not ticker:
                    continue
                ticker_opinions[ticker].append({
                    "analyst": analyst_name,
                    "action": pick.get("action", "HOLD"),
                    "conviction": pick.get("conviction", "LOW"),
                    "reasoning": pick.get("reasoning", ""),
                    "time_horizon": pick.get("time_horizon", ""),
                })

            for avoid in result.get("avoid_list", []):
                ticker = avoid.get("ticker", "") if isinstance(avoid, dict) else avoid
                reason = avoid.get("reason", "") if isinstance(avoid, dict) else ""
                if not ticker:
                    continue
                ticker_opinions[ticker].append({
                    "analyst": analyst_name,
                    "action": "SELL",
                    "conviction": "MEDIUM",
                    "reasoning": reason,
                })

        # Find consensus
        consensus_buys = []
        consensus_sells = []
        disagreements = []
        all_picks = {}

        for ticker, opinions in ticker_opinions.items():
            buy_opinions = [o for o in opinions if o["action"] == "BUY"]
            sell_opinions = [o for o in opinions if o["action"] in ("SELL", "AVOID")]
            hold_opinions = [o for o in opinions if o["action"] == "HOLD"]

            all_picks[ticker] = {
                "buy_count": len(buy_opinions),
                "sell_count": len(sell_opinions),
                "hold_count": len(hold_opinions),
                "opinions": opinions,
            }

            if len(buy_opinions) >= self.consensus_threshold:
                consensus_buys.append({
                    "ticker": ticker,
                    "buy_count": len(buy_opinions),
                    "analysts": [o["analyst"] for o in buy_opinions],
                    "convictions": [o["conviction"] for o in buy_opinions],
                    "reasonings": {o["analyst"]: o["reasoning"] for o in buy_opinions},
                })

            if len(sell_opinions) >= self.consensus_threshold:
                consensus_sells.append({
                    "ticker": ticker,
                    "sell_count": len(sell_opinions),
                    "analysts": [o["analyst"] for o in sell_opinions],
                    "reasonings": {o["analyst"]: o["reasoning"] for o in sell_opinions},
                })

            # Disagreements: significant buy AND sell opinions
            if len(buy_opinions) >= 2 and len(sell_opinions) >= 2:
                disagreements.append({
                    "ticker": ticker,
                    "bulls": [{"analyst": o["analyst"], "reasoning": o["reasoning"]} for o in buy_opinions],
                    "bears": [{"analyst": o["analyst"], "reasoning": o["reasoning"]} for o in sell_opinions],
                })

        # Sort by consensus strength
        consensus_buys.sort(key=lambda x: x["buy_count"], reverse=True)
        consensus_sells.sort(key=lambda x: x["sell_count"], reverse=True)

        return {
            "consensus_buys": consensus_buys,
            "consensus_sells": consensus_sells,
            "disagreements": disagreements,
            "all_picks": all_picks,
        }

    def _llm_synthesis(self, analyst_results: list[dict], mechanical: dict, market_briefing: str) -> dict:
        """Use Claude to synthesize a narrative report from all analyst outputs."""
        system_prompt = """You are the Chief Investment Strategist synthesizing opinions from 7 legendary investors.

Your job is to:
1. Identify the strongest consensus signals (where multiple analysts agree)
2. Highlight the most interesting disagreements and explain why they matter
3. Synthesize a clear market outlook based on all perspectives
4. Produce 3-5 actionable investment ideas with clear reasoning
5. Flag key risks that multiple analysts identified

Be balanced, clear, and actionable. Don't just summarize — add value by finding patterns and insights that individual analysts might miss.

Respond with valid JSON in this format:
{
  "market_overview": "2-3 paragraph synthesis of the overall market environment, drawing from multiple analyst perspectives",
  "strongest_signals": [
    {
      "ticker": "SYMBOL",
      "direction": "BUY" | "SELL",
      "confidence": "HIGH" | "MEDIUM",
      "synthesis": "Why this is a strong signal, citing which analysts agree and why"
    }
  ],
  "action_ideas": [
    {
      "idea": "Specific actionable idea (e.g., 'Consider adding AAPL on next 3% dip')",
      "rationale": "Why this idea makes sense given the analyst consensus",
      "risk": "Key risk to watch"
    }
  ],
  "key_risks": [
    "Risk 1 identified by multiple analysts",
    "Risk 2"
  ],
  "interesting_debates": [
    {
      "topic": "e.g., 'TSLA valuation'",
      "bull_case": "Summary of bullish analysts' views",
      "bear_case": "Summary of bearish analysts' views",
      "implication": "What this disagreement means for investors"
    }
  ]
}"""

        # Build the context with all analyst outputs
        analyst_summary = ""
        for result in analyst_results:
            analyst_summary += f"\n\n=== {result.get('analyst', 'Unknown')} ===\n"
            analyst_summary += f"Market Outlook: {result.get('market_outlook', 'N/A')}\n"
            analyst_summary += f"Top Picks:\n"
            for pick in result.get("top_picks", []):
                analyst_summary += (
                    f"  - {pick.get('ticker')}: {pick.get('action')} "
                    f"(Conviction: {pick.get('conviction')}) — {pick.get('reasoning', '')}\n"
                )
            analyst_summary += f"Avoid:\n"
            for avoid in result.get("avoid_list", []):
                if isinstance(avoid, dict):
                    analyst_summary += f"  - {avoid.get('ticker')}: {avoid.get('reason', '')}\n"
                else:
                    analyst_summary += f"  - {avoid}\n"
            analyst_summary += f"Key Observations:\n"
            for obs in result.get("key_observations", []):
                analyst_summary += f"  - {obs}\n"

        # Include mechanical consensus info
        consensus_info = f"\n\n=== MECHANICAL CONSENSUS ===\n"
        consensus_info += f"Consensus Buys ({self.consensus_threshold}+ analysts agree):\n"
        for cb in mechanical["consensus_buys"]:
            consensus_info += f"  - {cb['ticker']}: {cb['buy_count']} analysts ({', '.join(cb['analysts'])})\n"
        consensus_info += f"\nConsensus Sells:\n"
        for cs in mechanical["consensus_sells"]:
            consensus_info += f"  - {cs['ticker']}: {cs['sell_count']} analysts ({', '.join(cs['analysts'])})\n"
        consensus_info += f"\nDisagreements:\n"
        for d in mechanical["disagreements"]:
            bulls = ", ".join(b["analyst"] for b in d["bulls"])
            bears = ", ".join(b["analyst"] for b in d["bears"])
            consensus_info += f"  - {d['ticker']}: Bulls ({bulls}) vs Bears ({bears})\n"

        user_message = (
            f"Here is today's market data and all 7 analyst opinions. "
            f"Synthesize them into a final report.\n\n"
            f"=== MARKET DATA ===\n{market_briefing[:3000]}\n"
            f"{analyst_summary}\n{consensus_info}"
        )

        try:
            result, _meta = self.llm.generate_json(system_prompt, user_message)
            return result

        except Exception as e:
            logger.error(f"Aggregator LLM synthesis failed: {e}")
            return {
                "market_overview": "Synthesis unavailable due to error.",
                "strongest_signals": [],
                "action_ideas": [],
                "key_risks": [f"Aggregation error: {e}"],
                "interesting_debates": [],
            }
