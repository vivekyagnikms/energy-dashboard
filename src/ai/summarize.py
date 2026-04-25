"""Auto-summary feature. Narrative analyst commentary for one (region, product).

Implementation pattern:
- Deterministic data assembly first: pull history, compute KPIs, look up
  trend/range/recent moves. The LLM never asks for or invents these — we
  feed them as ground truth in the prompt.
- Gemini structured output (response_schema with Pydantic) so the JSON
  shape is guaranteed parseable. Fallback to a deterministic template if
  parsing fails or Gemini is unavailable.
- On-demand only: triggered by an explicit button in the UI, not on every
  region change. Conserves the 5 RPM free-tier quota.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass

import pandas as pd
from google.genai import types as genai_types
from pydantic import BaseModel, Field, ValidationError

from src.ai.client import GeminiClient, GeminiUnavailable
from src.ai.mock import SUMMARY_FALLBACK
from src.data.regions import REGIONS_BY_CODE
from src.data.schema import Product
from src.forecast.engine import ForecastEngine
from src.kpis.calculators import compute_kpi_set

logger = logging.getLogger(__name__)


class AutoSummary(BaseModel):
    """Pydantic model that doubles as the Gemini response_schema. The model
    must return JSON matching this shape; we then parse and render."""
    summary: str = Field(description="2-3 sentence narrative for a BD analyst.")
    top_drivers: list[str] = Field(
        description="2-4 bullet points naming the main forces shaping the trend.",
        min_length=1,
        max_length=5,
    )
    caveats: list[str] = Field(
        description="0-3 important caveats: data quality, assumption sensitivity, etc.",
        max_length=4,
        default_factory=list,
    )
    confidence: str = Field(description="One of: low, medium, high.")


@dataclass(frozen=True)
class SummaryResult:
    """What the UI receives. is_mock distinguishes live LLM output from fallback."""
    summary: str
    top_drivers: list[str]
    caveats: list[str]
    confidence: str
    is_mock: bool = False


# ---------- prompt assembly ----------


def _assemble_grounding(
    df: pd.DataFrame,
    engine: ForecastEngine,
    region_code: str,
    product: str,
    selected_year: int,
) -> dict:
    """Build the deterministic data dictionary fed to the LLM as ground truth."""
    region = REGIONS_BY_CODE.get(region_code)
    region_name = region.name if region else region_code
    pretty_product = "crude oil" if product == Product.CRUDE_OIL else "natural gas"
    unit = "MBBL" if product == Product.CRUDE_OIL else "MMCF"

    history = engine.history(region_code, product)
    if history.empty:
        return {
            "region": region_name,
            "product": pretty_product,
            "unit": unit,
            "has_data": False,
        }

    last_year = int(history["year"].iloc[-1])
    last_value = float(history["value"].iloc[-1])
    first_year = int(history["year"].iloc[0])
    first_value = float(history["value"].iloc[0])

    kpis = compute_kpi_set(df, engine, region_code, product, selected_year)

    # Forecast for selected_year (and last_year + 5 if different).
    fc_selected = None
    try:
        fc_selected = asdict(engine.forecast(region_code, product, selected_year)) \
            if selected_year > last_year else None
    except Exception:
        fc_selected = None
    fc_horizon = None
    try:
        fc_horizon = asdict(engine.forecast(region_code, product, last_year + 5))
    except Exception:
        fc_horizon = None

    return {
        "region": region_name,
        "product": pretty_product,
        "unit": unit,
        "has_data": True,
        "selected_year": int(selected_year),
        "history_first": {"year": first_year, "value": round(first_value, 2)},
        "history_last": {"year": last_year, "value": round(last_value, 2)},
        "kpis": kpis.as_dict(),
        "forecast_for_selected_year": fc_selected,
        "forecast_5y_horizon": fc_horizon,
    }


SUMMARY_SYSTEM_PROMPT: str = """\
You are an analyst writing a brief commentary for a U.S. oil-and-gas
business-development analyst.

You are GIVEN deterministic data for one region in JSON form. DO NOT invent
or alter any numbers; only describe and contextualize what is in the data.

Output JSON matching the requested schema:
- summary: 2-3 plain sentences. Reference the unit at least once.
- top_drivers: 2-4 short bullet points naming forces (production trend
  direction, volatility, share of national, recent acceleration/deceleration,
  etc.). DO NOT make up policy or geopolitical claims; describe what the
  numbers say.
- caveats: 0-3 honest cautions (low R^2, high volatility, partial-year data,
  forecast extrapolation distance, illustrative price assumption).
- confidence: 'low' if R^2 < 0.5 or n_training_years < 8 or volatility > 1;
  'high' if R^2 > 0.85 and n_training_years >= 12; otherwise 'medium'.
"""


# ---------- public API ----------


def summarize_region(
    client: GeminiClient,
    df: pd.DataFrame,
    engine: ForecastEngine,
    region_code: str,
    product: str,
    selected_year: int,
) -> SummaryResult:
    """Generate the narrative summary. Falls back to a deterministic template
    if Gemini is unavailable or returns malformed JSON."""
    grounding = _assemble_grounding(df, engine, region_code, product, selected_year)

    if not grounding.get("has_data"):
        # Empty-state region; return a deterministic message.
        return SummaryResult(
            summary=(
                f"{grounding['region']} does not have meaningful "
                f"{grounding['product']} production in EIA data."
            ),
            top_drivers=["No data available for this region/product combination."],
            caveats=[],
            confidence="high",
        )

    if client.mock or not client.is_available():
        return _fallback_from_grounding(grounding)

    user_prompt = "Data:\n" + json.dumps(grounding, indent=2)
    try:
        resp = client.generate(
            contents=[
                genai_types.Content(
                    role="user", parts=[genai_types.Part(text=user_prompt)]
                )
            ],
            system_instruction=SUMMARY_SYSTEM_PROMPT,
            response_schema=AutoSummary,
            response_mime_type="application/json",
        )
    except GeminiUnavailable as e:
        logger.warning("summarize_region: Gemini unavailable; using fallback: %s", e)
        return _fallback_from_grounding(grounding)

    raw_text = (resp.text or "").strip() if hasattr(resp, "text") else ""
    if not raw_text and resp.candidates:
        # Fallback: pull text from parts.
        parts = resp.candidates[0].content.parts if resp.candidates[0].content else []
        raw_text = "".join(getattr(p, "text", "") or "" for p in parts)

    try:
        parsed = AutoSummary.model_validate_json(raw_text)
    except (ValidationError, ValueError) as e:
        logger.warning("summarize_region: parse failed (%s); using fallback", e)
        return _fallback_from_grounding(grounding)

    return SummaryResult(
        summary=parsed.summary,
        top_drivers=parsed.top_drivers,
        caveats=parsed.caveats,
        confidence=parsed.confidence,
    )


def _fallback_from_grounding(g: dict) -> SummaryResult:
    """Deterministic 'no LLM' summary built from the grounding data alone."""
    if not g.get("has_data"):
        return SummaryResult(
            summary=f"{g['region']} does not have {g['product']} production data.",
            top_drivers=[],
            caveats=[],
            confidence="high",
            is_mock=True,
        )
    first = g["history_first"]
    last = g["history_last"]
    delta = last["value"] - first["value"]
    direction = "grown" if delta > 0 else ("declined" if delta < 0 else "held flat")
    pct = (delta / first["value"]) * 100 if first["value"] else 0.0
    summary = (
        f"{g['region']} {g['product']} production has {direction} by {abs(pct):.1f}% "
        f"between {first['year']} and {last['year']} "
        f"(from {first['value']:,.0f} to {last['value']:,.0f} {g['unit']})."
    )
    drivers = [
        f"Most recent observation: {last['year']} = {last['value']:,.0f} {g['unit']}.",
    ]
    if g.get("forecast_5y_horizon"):
        f5 = g["forecast_5y_horizon"]
        drivers.append(
            f"5-year-ahead forecast ({f5['target_year']}): {f5['value']:,.0f} {g['unit']} "
            f"(R² {f5['r_squared']:.2f})."
        )
    fallback = SUMMARY_FALLBACK
    return SummaryResult(
        summary=summary,
        top_drivers=drivers,
        caveats=fallback["caveats"],
        confidence="medium",
        is_mock=True,
    )
