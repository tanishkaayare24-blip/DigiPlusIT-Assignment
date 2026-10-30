"""AI provider clients. Each one takes a system + user prompt and returns raw text plus token usage."""
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings
from app.core.constants import AI_MAX_TOKENS


class AIRefusalError(Exception):
    pass


class AIClient(Protocol):
    provider: str
    model: str

    def complete_json(self, system: str, user: str) -> tuple[str, dict]:
        """Return (raw_text, usage_dict)."""


class AnthropicClient:
    provider = "anthropic"

    def __init__(self, api_key: str, model: str, timeout: float):
        import anthropic

        self.model = model
        # Retries are handled by ai/runner.py so every attempt is logged.
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=0)

    def complete_json(self, system: str, user: str) -> tuple[str, dict]:
        extra = {} if self.model.startswith("claude-haiku") else {"output_config": {"effort": "low"}}
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=AI_MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
            **extra,
        )
        if resp.stop_reason == "refusal":
            raise AIRefusalError("model declined the request")
        text = "".join(block.text for block in resp.content if block.type == "text")
        usage = {"tokens_in": resp.usage.input_tokens, "tokens_out": resp.usage.output_tokens}
        return text, usage


class GeminiClient:
    provider = "gemini"

    def __init__(self, api_key: str, model: str, timeout: float):
        from google import genai
        from google.genai import types

        self.model = model
        self._types = types
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout * 1000)))

    def complete_json(self, system: str, user: str) -> tuple[str, dict]:
        resp = self._client.models.generate_content(
            model=self.model,
            contents=user,
            config=self._types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                temperature=0.2,
                max_output_tokens=AI_MAX_TOKENS * 2,
            ),
        )
        meta = resp.usage_metadata
        usage = {"tokens_in": getattr(meta, "prompt_token_count", None),
                 "tokens_out": getattr(meta, "candidates_token_count", None)}
        return resp.text or "", usage


_PROVIDERS = {"anthropic": AnthropicClient, "gemini": GeminiClient}


@lru_cache
def get_ai_client() -> AIClient | None:
    """Return the configured provider, or None when no AI is configured (app runs in basic mode)."""
    settings = get_settings()
    if not settings.ai_configured:
        return None
    cls = _PROVIDERS[settings.ai_provider.lower()]
    return cls(settings.ai_api_key, settings.resolved_model, settings.ai_timeout_seconds)
