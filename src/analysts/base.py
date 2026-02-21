"""Base analyst agent with Claude API integration."""

import json
import logging
import os

import anthropic

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
        analyst_config = config.get("analysts", {})
        self.model = os.getenv("CLAUDE_MODEL", analyst_config.get("model", "claude-sonnet-4-20250514"))
        self.max_tokens = analyst_config.get("max_tokens", 4096)
        self.temperature = analyst_config.get("temperature", 0.3)
        self.client = anthropic.Anthropic()

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
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )

            response_text = response.content[0].text.strip()

            # Parse JSON from response (handle potential markdown wrapping)
            json_text = response_text
            if json_text.startswith("```"):
                # Strip markdown code fences
                lines = json_text.split("\n")
                json_text = "\n".join(
                    line for line in lines
                    if not line.strip().startswith("```")
                )

            result = json.loads(json_text)
            result["_meta"] = {
                "model": self.model,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }

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
                "raw_response": response_text[:1000] if 'response_text' in dir() else "No response",
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
