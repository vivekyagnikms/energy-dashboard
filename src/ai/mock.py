"""Canned responses for MOCK_AI=true development and circuit-breaker fallback.

Used in two scenarios:
1. Local development without burning Gemini quota (set MOCK_AI=true).
2. Live demo when the free Gemini tier is exhausted (circuit breaker
   in client.py flips, ChatRunner returns one of these instead of erroring).
"""

from __future__ import annotations

from typing import Final


MOCK_BANNER: Final[str] = (
    "🤖 *Mock-mode response shown — the live AI is currently rate-limited or disabled.*"
)


CHAT_FALLBACK_TEXT: Final[str] = (
    f"{MOCK_BANNER}\n\n"
    "I can normally answer questions about U.S. oil and gas production by "
    "querying the live data and forecasts shown on this page. While the AI "
    "is unavailable, the KPI cards and chart on this page are still fully "
    "live — every number above came from the same EIA data the AI uses."
)


SUMMARY_FALLBACK: Final[dict] = {
    "summary": "Live data is shown on this page. (Mock-mode placeholder while AI is rate-limited.)",
    "top_drivers": [
        "See the chart on this page for the multi-year production trend.",
        "KPI cards above show YoY growth, 5-year CAGR, and volatility for the selected year.",
    ],
    "caveats": [
        "This is a mock-mode summary; the live narrative is unavailable right now."
    ],
    "confidence": "low",
}


ANOMALY_FALLBACK_TEXT: Final[str] = (
    f"{MOCK_BANNER}\n\n"
    "Anomalies were flagged statistically (z-score on year-over-year % change). "
    "Detailed narrative explanations are not available in mock mode — but the "
    "flagged years are listed above with their z-scores and YoY values for "
    "your interpretation."
)
