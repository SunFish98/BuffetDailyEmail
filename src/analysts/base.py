"""Base analyst agent with multi-provider LLM integration (Claude / Gemini)."""

import json
import logging
import os

from ..llm_client import LLMClient

logger = logging.getLogger(__name__)

# Shared output format instructions for all analysts
OUTPUT_FORMAT_INSTRUCTIONS = """
You MUST respond with valid JSON in this exact format:
{
  "analyst": "<your investor persona name>",
  "market_outlook": "A 2-3 sentence overall market assessment from your philosophical perspective",
  "top_picks": [
    {
      "ticker": "SYMBOL",
      "action": "BUY" | "HOLD" | "SELL",
      "conviction": "HIGH" | "MEDIUM" | "LOW",
      "reasoning": "2-3 sentences explaining your rationale using your specific investment principles",
      "time_horizon": "e.g., '5+ years', '1-3 years', '3-6 months'"
    }
  ],
  "avoid_list": [
    {
      "ticker": "SYMBOL",
      "reason": "Brief explanation of why to avoid"
    }
  ],
  "key_observations": [
    "Important observation 1 from your analytical framework",
    "Important observation 2"
  ]
}

Rules:
- Include 3-7 top picks (only include stocks you have a strong opinion on)
- Include 1-5 stocks to avoid
- Include 2-5 key observations
- Be specific and reference actual data points from the briefing
- Stay true to your investment philosophy - don't just agree with conventional wisdom
- If data is insufficient to form an opinion on a stock, skip it
- ONLY output valid JSON, no other text
"""


class BaseAnalyst:
    """Base class for all analyst agents."""

    # Subclasses must override these
    name: str = "Base Analyst"
    philosophy_prompt: str = "You are a stock analyst."

    def __init__(self, config: dict):
        self.config = config
        self.llm = LLMClient(config)

    def analyze(self, market_briefing: str) -> dict:
        """Run analysis on the market briefing data.

        Args:
            market_briefing: Full text briefing from DataCollector.prepare_full_context()

        Returns:
            Parsed JSON dict with analyst's recommendations.
        """
        logger.info(f"Running {self.name} analysis...")

        system_prompt = f"{self.philosophy_prompt}\n\n{OUTPUT_FORMAT_INSTRUCTIONS}"

        user_message = (
            f"Today's market data briefing is below. Analyze it thoroughly using your "
            f"investment philosophy and provide your recommendations.\n\n"
            f"{market_briefing}"
        )

        try:
            result, meta = self.llm.generate_json(system_prompt, user_message)
            result["_meta"] = meta

            logger.info(
                f"{self.name} analysis complete: "
                f"{len(result.get('top_picks', []))} picks, "
                f"{len(result.get('avoid_list', []))} avoids"
            )
            return result

        except json.JSONDecodeError as e:
            logger.error(f"{self.name} returned invalid JSON: {e}")
            return {
                "analyst": self.name,
                "error": f"Invalid JSON response: {e}",
                "top_picks": [],
                "avoid_list": [],
                "key_observations": [f"Analysis failed due to JSON parsing error"],
                "market_outlook": "Analysis error - could not parse response",
            }
        except Exception as e:
            logger.error(f"{self.name} analysis failed: {e}")
            return {
                "analyst": self.name,
                "error": str(e),
                "top_picks": [],
                "avoid_list": [],
                "key_observations": [f"Analysis failed: {e}"],
                "market_outlook": "Analysis error",
            }
