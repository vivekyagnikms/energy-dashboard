"""Gemini API client wrapper with rate-limit handling and a mock toggle.

Layers:
- Real Gemini calls via google-genai (when MOCK_AI=false and key present).
- Exponential-backoff retry on 429 / transient errors.
- Per-session call counter + circuit breaker that swaps to mock responses
  when the free-tier quota is exhausted (so the live demo never hard-fails
  during judging).
- MOCK_AI=true bypass for development and testing.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from google import genai
from google.genai import types as genai_types

logger = logging.getLogger(__name__)

# Model selection. Pin the version so deploy behavior is reproducible.
# Note: Google has migrated free-tier quotas across models; if a 429 with
# "limit: 0" appears, swap to one of the alternatives in MODEL_FALLBACKS.
MODEL_NAME: str = "gemini-2.5-flash"
MODEL_FALLBACKS: tuple[str, ...] = (
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
)

# Per-session circuit breaker. After this many tool-call iterations within
# a single chat turn, we stop the loop and return what we have so far.
MAX_TOOL_CALLS_PER_TURN: int = 5

# Retry budget for rate-limit / transient failures.
MAX_RETRIES: int = 3
INITIAL_BACKOFF_SECONDS: float = 1.0


@dataclass
class GeminiCallStats:
    """Light-touch usage tracker. We do not bother with token-level counting
    on the free tier — request count is the meaningful free-tier limit."""

    requests: int = 0
    rate_limit_hits: int = 0
    last_error: str | None = None
    circuit_open: bool = False  # set True after exhausting retries on a 429


class GeminiUnavailable(Exception):
    """Raised when Gemini is unreachable AND we have no fallback path."""


class GeminiClient:
    """Thin wrapper around google-genai. Owns a single Client instance and
    a stats object the UI can read for the 'Show grounding' panel.
    """

    def __init__(self, api_key: str | None, *, mock: bool = False) -> None:
        self.mock = mock
        self.stats = GeminiCallStats()
        if mock:
            self._client: genai.Client | None = None
            return
        if not api_key:
            raise ValueError("GEMINI_API_KEY missing; pass mock=True for offline mode")
        self._client = genai.Client(api_key=api_key)

    # ----- low-level: one model call with retries -----

    def generate(
        self,
        *,
        contents: list[genai_types.Content],
        system_instruction: str | None = None,
        tools: list[genai_types.Tool] | None = None,
        response_schema: type | None = None,
        response_mime_type: str | None = None,
    ) -> genai_types.GenerateContentResponse:
        """Single Gemini call with retry/backoff. Returns the raw response.

        Caller is responsible for inspecting the response for function_calls
        vs final text and looping appropriately (see chat.py).
        """
        if self.mock or self._client is None:
            raise GeminiUnavailable(
                "client is in mock mode; do not call generate() directly"
            )

        config_kwargs: dict = {}
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if tools:
            config_kwargs["tools"] = tools
        if response_schema is not None:
            config_kwargs["response_schema"] = response_schema
        if response_mime_type is not None:
            config_kwargs["response_mime_type"] = response_mime_type
        config = genai_types.GenerateContentConfig(**config_kwargs)

        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self.stats.requests += 1
                resp = self._client.models.generate_content(
                    model=MODEL_NAME,
                    contents=contents,
                    config=config,
                )
                return resp
            except Exception as e:
                last_error = e
                msg = str(e).lower()
                is_rate_limit = (
                    "429" in msg
                    or "rate" in msg
                    or "quota" in msg
                    or "resource_exhausted" in msg
                )
                if is_rate_limit:
                    self.stats.rate_limit_hits += 1
                if attempt < MAX_RETRIES:
                    sleep_for = INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1))
                    logger.warning(
                        "Gemini call failed (attempt %d/%d): %s — retrying in %.1fs",
                        attempt,
                        MAX_RETRIES,
                        e,
                        sleep_for,
                    )
                    time.sleep(sleep_for)
                    continue
                # Final failure: open the circuit so the next call short-circuits to mock.
                self.stats.circuit_open = True
                self.stats.last_error = str(e)
                raise GeminiUnavailable(
                    f"Gemini unavailable after {MAX_RETRIES} attempts: {e}"
                ) from last_error

        # Defensive — should be unreachable.
        raise GeminiUnavailable(f"Gemini unavailable: {last_error}")

    def is_available(self) -> bool:
        """True if real calls are likely to succeed (not mocked, not circuit-open)."""
        return (
            not self.mock and not self.stats.circuit_open and self._client is not None
        )
