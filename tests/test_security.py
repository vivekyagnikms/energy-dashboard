"""Security tests: input sanitization, log redaction, refusal detection.

We verify:
- length cap on user input
- control characters stripped
- whitespace-only inputs become empty
- API-key-shaped tokens redacted from log strings
- refusal prefix detected by chat layer (string contract test)
"""
from __future__ import annotations

import pytest

from src.ai.chat import REFUSAL_PREFIX, _cross_check_numbers, ToolCallRecord
from src.utils.security import (
    MAX_USER_INPUT_CHARS,
    sanitize_for_log,
    sanitize_user_text,
)


# ---------- input sanitization ----------


def test_input_clip_to_max_chars():
    big = "x" * (MAX_USER_INPUT_CHARS + 500)
    out = sanitize_user_text(big)
    assert len(out) == MAX_USER_INPUT_CHARS


def test_input_strips_control_characters():
    s = "hello\x00world\x07!"
    assert sanitize_user_text(s) == "helloworld!"


def test_whitespace_only_input_becomes_empty():
    assert sanitize_user_text("   \t\n  ") == ""


def test_none_input_returns_empty_string():
    assert sanitize_user_text(None) == ""


def test_input_keeps_normal_punctuation_and_unicode():
    s = "Hello — what was Texas's crude oil production in 2022? 🛢️"
    assert sanitize_user_text(s) == s


# ---------- log redaction ----------


def test_log_redacts_api_key_tokens():
    msg = "Failure: api_key=AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ012345 not allowed"
    out = sanitize_for_log(msg)
    assert "AIzaSy" not in out
    assert "REDACTED" in out


def test_log_redacts_bearer_tokens():
    msg = "Authorization: bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9_xxxxxxxxx"
    out = sanitize_for_log(msg)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9_xxxxxxxxx" not in out
    assert "REDACTED" in out


def test_log_passthrough_for_safe_messages():
    msg = "Forecast for Texas crude oil 2030 = 2,819,983 MBBL"
    assert sanitize_for_log(msg) == msg


# ---------- refusal detection contract ----------


def test_refusal_prefix_constant_unchanged():
    """Tests the prompt-engineering contract: if this constant changes
    without updating the system prompt, the refusal detection breaks."""
    assert REFUSAL_PREFIX == "REFUSAL:"


# ---------- number cross-check guardrail ----------


def test_unverified_numbers_detected():
    # Tool returned 100.0; LLM claims 999.0 — should be flagged as unverified.
    rec = ToolCallRecord(name="get_production", args={},
                         result={"data": {"value": 100.0}, "ok": True})
    answer = "Production was 999 MBBL in 2022."
    unverified = _cross_check_numbers(answer, [rec])
    assert "999" in unverified


def test_verified_numbers_not_flagged():
    rec = ToolCallRecord(name="get_production", args={},
                         result={"data": {"value": 1234567.89}})
    answer = "Production reached 1,234,568 MBBL."  # rounded version of 1234567.89
    unverified = _cross_check_numbers(answer, [rec])
    assert unverified == []


def test_year_tokens_are_not_treated_as_unverified_figures():
    rec = ToolCallRecord(name="get_production", args={}, result={"data": {"value": 1000.0}})
    answer = "Texas produced about 1,000 MBBL in 2022."
    unverified = _cross_check_numbers(answer, [rec])
    # 2022 should be skipped; 1000 is verified.
    assert unverified == []
