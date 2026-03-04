"""LLM client abstraction — supports Anthropic Claude and Google Gemini."""

import json
import logging
import os

logger = logging.getLogger(__name__)


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences from LLM response."""
    if text.startswith("```"):
        lines = text.split("\n")
        return "\n".join(line for line in lines if not line.strip().startswith("```"))
    return text


def get_llm_provider() -> str:
    """Determine which LLM provider to use based on environment config."""
    provider = os.getenv("LLM_PROVIDER", "anthropic").lower()
    if provider in ("google", "gemini"):
        return "gemini"
    return "anthropic"


def get_default_model(provider: str) -> str:
    """Get the default model for a given provider."""
    if provider == "gemini":
        return os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    return os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")


class LLMClient:
    """Unified LLM client that delegates to either Claude or Gemini."""

    def __init__(self, config: dict):
        self.provider = get_llm_provider()
        analyst_config = config.get("analysts", {})

        if self.provider == "gemini":
            self.model = os.getenv("GEMINI_MODEL", analyst_config.get("gemini_model", "gemini-2.5-flash"))
            self._init_gemini()
        else:
            self.model = os.getenv("CLAUDE_MODEL", analyst_config.get("model", "claude-sonnet-4-20250514"))
            self._init_anthropic()

        self.max_tokens = analyst_config.get("max_tokens", 4096)
        self.temperature = analyst_config.get("temperature", 0.3)

    def _init_anthropic(self):
        import anthropic
        self.client = anthropic.Anthropic()

    def _init_gemini(self):
        from google import genai
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set. Add it to your .env file.")
        self.client = genai.Client(api_key=api_key)

    def generate(self, system_prompt: str, user_message: str) -> tuple[str, dict]:
        """Send a prompt to the LLM and return (response_text, usage_meta).

        Args:
            system_prompt: System-level instructions.
            user_message: The user message / data to analyze.

        Returns:
            Tuple of (response_text, meta_dict).
            meta_dict contains model, input_tokens, output_tokens.
        """
        if self.provider == "gemini":
            return self._generate_gemini(system_prompt, user_message)
        return self._generate_anthropic(system_prompt, user_message)

    def _generate_anthropic(self, system_prompt: str, user_message: str) -> tuple[str, dict]:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        text = response.content[0].text.strip()
        meta = {
            "model": self.model,
            "provider": "anthropic",
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }
        return text, meta

    def _generate_gemini(self, system_prompt: str, user_message: str) -> tuple[str, dict]:
        from google.genai import types

        response = self.client.models.generate_content(
            model=self.model,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=self.temperature,
                max_output_tokens=self.max_tokens,
            ),
        )
        text = response.text.strip()
        usage = response.usage_metadata
        meta = {
            "model": self.model,
            "provider": "gemini",
            "input_tokens": getattr(usage, "prompt_token_count", 0),
            "output_tokens": getattr(usage, "candidates_token_count", 0),
        }
        return text, meta

    def generate_json(self, system_prompt: str, user_message: str) -> tuple[dict, dict]:
        """Generate and parse a JSON response. Returns (parsed_dict, meta)."""
        text, meta = self.generate(system_prompt, user_message)
        json_text = _strip_code_fences(text)
        return json.loads(json_text), meta
