"""Aggregator agent — synthesizes all analyst opinions into a final report."""

import json
import logging
import os
from collections import defaultdict

from ..llm_client import LLMClient

logger = logging.getLogger(__name__)

# Conviction multipliers for weighted scoring
CONVICTION_WEIGHTS = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}

# Horizon labels for display
HORIZON_LABELS = {
    "short": "Short-term (weeks-months)",
    "medium": "Medium-term (months-years)",
    "long": "Long-term (years+)",
}


class Aggregator:
    """Aggregates all analyst outputs into a final investment intelligence report."""

    def __init__(self, config: dict):
        self.config = config
        agg_config = config.get("aggregator", {})
        self.consensus_threshold = agg_config.get("consensus_threshold", 3)
        self.weights = agg_config.get("weights", {})
        self.llm = LLMClient(config)

    def aggregate(self, analyst_results: list[dict], market_briefing: str,
                  scorecard: dict | None = None) -> dict:
        """Aggregate all analyst results into a final report.

        Args:
            analyst_results: List of dicts from each analyst's analyze() call.
            market_briefing: The original market data briefing text.
            scorecard: Optional analyst accuracy scorecard from HistoryTracker.

        Returns:
            Final aggregated report dict.
        """
        logger.info(f"Aggregating results from {len(analyst_results)} analysts")

        # Build accuracy weights from scorecard (if available)
        accuracy_weights = self._build_accuracy_weights(scorecard)

        # Step 1: Weighted mechanical aggregation
        mechanical = self._mechanical_aggregation(analyst_results, accuracy_weights)

        # Step 2: LLM synthesis with horizon separation and accuracy context
        synthesis = self._llm_synthesis(
            analyst_results, mechanical, market_briefing,
            accuracy_weights, scorecard,
        )

        return {
            "consensus_buys": mechanical["consensus_buys"],
            "consensus_sells": mechanical["consensus_sells"],
            "disagreements": mechanical["disagreements"],
            "all_picks": mechanical["all_picks"],
            "horizon_consensus": mechanical["horizon_consensus"],
            "synthesis": synthesis,
            "analyst_summaries": [
                {
                    "analyst": r.get("analyst", "Unknown"),
                    "market_outlook": r.get("market_outlook", ""),
                    "pick_count": len(r.get("top_picks", [])),
                    "avoid_count": len(r.get("avoid_list", [])),
                    "horizon": r.get("_horizon", "medium"),
                    "accuracy_weight": accuracy_weights.get(r.get("analyst", ""), 1.0),
                }
                for r in analyst_results
            ],
        }

    def _build_accuracy_weights(self, scorecard: dict | None) -> dict:
        """Convert scorecard accuracy into per-analyst weights.

        Analysts with more accurate historical picks get higher weight.
        New analysts (no history) get a neutral weight of 1.0.
        Weights range from 0.5 (very poor track record) to 2.0 (excellent).
        """
        if not scorecard:
            return {}

        weights = {}
        for analyst, sc in scorecard.items():
            if sc["total"] < 3:
                # Not enough history to judge — neutral weight
                weights[analyst] = 1.0
                continue
            # Map 0-100% accuracy to 0.5-2.0 weight
            accuracy = sc["accuracy_pct"] / 100.0
            weights[analyst] = 0.5 + (accuracy * 1.5)

        if weights:
            logger.info(
                "Accuracy weights: "
                + ", ".join(f"{a}: {w:.2f}" for a, w in sorted(weights.items()))
            )

        return weights

    def _opinion_score(self, opinion: dict, accuracy_weights: dict) -> float:
        """Calculate a weighted score for a single opinion.

        Combines conviction level and historical accuracy.
        """
        conviction_w = CONVICTION_WEIGHTS.get(opinion.get("conviction", "LOW"), 1)
        accuracy_w = accuracy_weights.get(opinion["analyst"], 1.0)
        return conviction_w * accuracy_w

    def _mechanical_aggregation(self, analyst_results: list[dict],
                                accuracy_weights: dict) -> dict:
        """Find consensus and disagreements across analysts, weighted by conviction and accuracy."""
        ticker_opinions = defaultdict(list)

        for result in analyst_results:
            analyst_name = result.get("analyst", "Unknown")
            horizon = result.get("_horizon", "medium")

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
                    "analyst_horizon": horizon,
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
                    "analyst_horizon": horizon,
                })

        # Find consensus using weighted scoring
        consensus_buys = []
        consensus_sells = []
        disagreements = []
        all_picks = {}

        for ticker, opinions in ticker_opinions.items():
            buy_opinions = [o for o in opinions if o["action"] == "BUY"]
            sell_opinions = [o for o in opinions if o["action"] in ("SELL", "AVOID")]
            hold_opinions = [o for o in opinions if o["action"] == "HOLD"]

            # Weighted scores
            buy_score = sum(self._opinion_score(o, accuracy_weights) for o in buy_opinions)
            sell_score = sum(self._opinion_score(o, accuracy_weights) for o in sell_opinions)

            all_picks[ticker] = {
                "buy_count": len(buy_opinions),
                "sell_count": len(sell_opinions),
                "hold_count": len(hold_opinions),
                "buy_score": round(buy_score, 2),
                "sell_score": round(sell_score, 2),
                "opinions": opinions,
            }

            if len(buy_opinions) >= self.consensus_threshold:
                consensus_buys.append({
                    "ticker": ticker,
                    "buy_count": len(buy_opinions),
                    "weighted_score": round(buy_score, 2),
                    "analysts": [o["analyst"] for o in buy_opinions],
                    "convictions": [o["conviction"] for o in buy_opinions],
                    "reasonings": {o["analyst"]: o["reasoning"] for o in buy_opinions},
                })

            if len(sell_opinions) >= self.consensus_threshold:
                consensus_sells.append({
                    "ticker": ticker,
                    "sell_count": len(sell_opinions),
                    "weighted_score": round(sell_score, 2),
                    "analysts": [o["analyst"] for o in sell_opinions],
                    "reasonings": {o["analyst"]: o["reasoning"] for o in sell_opinions},
                })

            if len(buy_opinions) >= 2 and len(sell_opinions) >= 2:
                disagreements.append({
                    "ticker": ticker,
                    "bulls": [{"analyst": o["analyst"], "reasoning": o["reasoning"]} for o in buy_opinions],
                    "bears": [{"analyst": o["analyst"], "reasoning": o["reasoning"]} for o in sell_opinions],
                })

        # Sort by weighted score (not just head count)
        consensus_buys.sort(key=lambda x: x["weighted_score"], reverse=True)
        consensus_sells.sort(key=lambda x: x["weighted_score"], reverse=True)

        # Horizon-separated consensus
        horizon_consensus = self._horizon_consensus(ticker_opinions, accuracy_weights)

        return {
            "consensus_buys": consensus_buys,
            "consensus_sells": consensus_sells,
            "disagreements": disagreements,
            "all_picks": all_picks,
            "horizon_consensus": horizon_consensus,
        }

    def _horizon_consensus(self, ticker_opinions: dict,
                           accuracy_weights: dict) -> dict:
        """Group consensus by investment horizon so short-term and long-term
        signals are reported separately."""
        horizons = {"short": defaultdict(list), "medium": defaultdict(list), "long": defaultdict(list)}

        for ticker, opinions in ticker_opinions.items():
            for o in opinions:
                h = o.get("analyst_horizon", "medium")
                horizons[h][ticker].append(o)

        result = {}
        for horizon, tickers in horizons.items():
            top_buys = []
            top_sells = []
            for ticker, opinions in tickers.items():
                buys = [o for o in opinions if o["action"] == "BUY"]
                sells = [o for o in opinions if o["action"] in ("SELL", "AVOID")]
                if buys:
                    score = sum(self._opinion_score(o, accuracy_weights) for o in buys)
                    top_buys.append({
                        "ticker": ticker,
                        "count": len(buys),
                        "score": round(score, 2),
                        "analysts": [o["analyst"] for o in buys],
                    })
                if sells:
                    score = sum(self._opinion_score(o, accuracy_weights) for o in sells)
                    top_sells.append({
                        "ticker": ticker,
                        "count": len(sells),
                        "score": round(score, 2),
                        "analysts": [o["analyst"] for o in sells],
                    })
            top_buys.sort(key=lambda x: x["score"], reverse=True)
            top_sells.sort(key=lambda x: x["score"], reverse=True)
            result[horizon] = {
                "label": HORIZON_LABELS[horizon],
                "buys": top_buys[:5],
                "sells": top_sells[:5],
            }

        return result

    def _llm_synthesis(self, analyst_results: list[dict], mechanical: dict,
                       market_briefing: str, accuracy_weights: dict,
                       scorecard: dict | None) -> dict:
        """Use the LLM to synthesize a narrative report from all analyst outputs."""
        num_analysts = len(analyst_results)
        system_prompt = f"""You are the Chief Investment Strategist synthesizing opinions from {num_analysts} legendary investors.

IMPORTANT CONTEXT:
- Each analyst has an investment HORIZON (short/medium/long). A short-term trader's BUY means something very different from a long-term value investor's BUY. You MUST separate recommendations by time horizon in your output.
- Opinions are WEIGHTED by historical accuracy and conviction level. Higher weighted scores indicate stronger, more reliable signals. Pay attention to the weighted scores.
- When analysts across DIFFERENT horizons agree on the same ticker and direction, that is an especially strong signal worth highlighting.

Your job is to:
1. Separate recommendations by time horizon (short/medium/long-term)
2. Identify the strongest weighted consensus signals
3. Highlight cross-horizon agreement (most valuable signal)
4. Produce actionable ideas appropriate for each time horizon
5. Flag key risks that multiple analysts identified

Respond with valid JSON in this format:
{{
  "market_overview": "2-3 paragraph synthesis of the overall market environment",
  "short_term_actions": [
    {{
      "ticker": "SYMBOL",
      "action": "BUY" | "SELL",
      "reasoning": "Why, citing which short-term analysts agree",
      "timeframe": "e.g., '2-6 weeks'"
    }}
  ],
  "medium_term_actions": [
    {{
      "ticker": "SYMBOL",
      "action": "BUY" | "SELL",
      "reasoning": "Why, citing which medium-term analysts agree",
      "timeframe": "e.g., '3-12 months'"
    }}
  ],
  "long_term_actions": [
    {{
      "ticker": "SYMBOL",
      "action": "BUY" | "SELL",
      "reasoning": "Why, citing which long-term analysts agree",
      "timeframe": "e.g., '2-5+ years'"
    }}
  ],
  "cross_horizon_signals": [
    {{
      "ticker": "SYMBOL",
      "direction": "BUY" | "SELL",
      "confidence": "HIGH" | "MEDIUM",
      "synthesis": "Why this is powerful — analysts across different time horizons agree"
    }}
  ],
  "key_risks": [
    "Risk 1 identified by multiple analysts",
    "Risk 2"
  ],
  "interesting_debates": [
    {{
      "topic": "e.g., 'TSLA valuation'",
      "bull_case": "Summary of bullish views",
      "bear_case": "Summary of bearish views",
      "implication": "What this means for investors"
    }}
  ]
}}"""

        # Build the context with all analyst outputs, including horizon tags
        analyst_summary = ""
        for result in analyst_results:
            name = result.get("analyst", "Unknown")
            horizon = result.get("_horizon", "medium")
            weight = accuracy_weights.get(name, 1.0)
            analyst_summary += f"\n\n=== {name} [Horizon: {horizon.upper()}] [Accuracy Weight: {weight:.2f}] ===\n"
            analyst_summary += f"Market Outlook: {result.get('market_outlook', 'N/A')}\n"
            analyst_summary += "Top Picks:\n"
            for pick in result.get("top_picks", []):
                analyst_summary += (
                    f"  - {pick.get('ticker')}: {pick.get('action')} "
                    f"(Conviction: {pick.get('conviction')}, "
                    f"Time Horizon: {pick.get('time_horizon', 'N/A')}) "
                    f"— {pick.get('reasoning', '')}\n"
                )
            analyst_summary += "Avoid:\n"
            for avoid in result.get("avoid_list", []):
                if isinstance(avoid, dict):
                    analyst_summary += f"  - {avoid.get('ticker')}: {avoid.get('reason', '')}\n"
                else:
                    analyst_summary += f"  - {avoid}\n"
            analyst_summary += "Key Observations:\n"
            for obs in result.get("key_observations", []):
                analyst_summary += f"  - {obs}\n"

        # Include weighted mechanical consensus info
        consensus_info = "\n\n=== WEIGHTED MECHANICAL CONSENSUS ===\n"
        consensus_info += f"Consensus Buys ({self.consensus_threshold}+ analysts agree, sorted by weighted score):\n"
        for cb in mechanical["consensus_buys"]:
            consensus_info += (
                f"  - {cb['ticker']}: {cb['buy_count']} analysts, "
                f"weighted score {cb['weighted_score']} "
                f"({', '.join(cb['analysts'])})\n"
            )
        consensus_info += "\nConsensus Sells:\n"
        for cs in mechanical["consensus_sells"]:
            consensus_info += (
                f"  - {cs['ticker']}: {cs['sell_count']} analysts, "
                f"weighted score {cs['weighted_score']} "
                f"({', '.join(cs['analysts'])})\n"
            )

        # Horizon-separated info
        consensus_info += "\n\n=== HORIZON-SEPARATED SIGNALS ===\n"
        for h in ("short", "medium", "long"):
            hdata = mechanical["horizon_consensus"].get(h, {})
            consensus_info += f"\n{HORIZON_LABELS.get(h, h)}:\n"
            consensus_info += "  Top Buys: "
            buys = hdata.get("buys", [])
            if buys:
                consensus_info += ", ".join(
                    f"{b['ticker']} (score {b['score']}, {', '.join(b['analysts'])})"
                    for b in buys
                )
            else:
                consensus_info += "None"
            consensus_info += "\n  Top Sells: "
            sells = hdata.get("sells", [])
            if sells:
                consensus_info += ", ".join(
                    f"{s['ticker']} (score {s['score']}, {', '.join(s['analysts'])})"
                    for s in sells
                )
            else:
                consensus_info += "None"
            consensus_info += "\n"

        # Scorecard context
        scorecard_info = ""
        if scorecard:
            scorecard_info = "\n\n=== ANALYST TRACK RECORD (past 30 days) ===\n"
            for analyst, sc in sorted(scorecard.items(), key=lambda x: x[1].get("accuracy_pct", 0), reverse=True):
                scorecard_info += (
                    f"  {analyst}: {sc['accuracy_pct']}% accurate "
                    f"({sc['correct']}/{sc['total']} picks), "
                    f"avg return {sc['avg_return']}%\n"
                )

        user_message = (
            f"Here is today's market data and all {num_analysts} analyst opinions. "
            f"Synthesize them into a final report with SEPARATE recommendations "
            f"for short-term, medium-term, and long-term investors.\n\n"
            f"=== MARKET DATA ===\n{market_briefing[:5000]}\n"
            f"{analyst_summary}\n{consensus_info}{scorecard_info}"
        )

        try:
            result, _meta = self.llm.generate_json(system_prompt, user_message)
            return result

        except Exception as e:
            logger.error(f"Aggregator LLM synthesis failed: {e}")
            return {
                "market_overview": "Synthesis unavailable due to error.",
                "short_term_actions": [],
                "medium_term_actions": [],
                "long_term_actions": [],
                "cross_horizon_signals": [],
                "key_risks": [f"Aggregation error: {e}"],
                "interesting_debates": [],
            }
