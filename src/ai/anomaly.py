"""Anomaly explanation feature.

Strict separation of concerns:
- DETECTION is statistical, in src/ai/tools.py::get_anomalies_impl. Anomalies
  are flagged by z-score (>=2.5σ on YoY % change). The LLM cannot add or
  remove flagged years.
- EXPLANATION is narrative, here. We feed the LLM the flagged-years payload
  and a structured-output schema; it returns one short explanation per year.
- Falls back to a deterministic template if Gemini is unavailable.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import pandas as pd
from google.genai import types as genai_types
from pydantic import BaseModel, Field, ValidationError

from src.ai.client import GeminiClient, GeminiUnavailable
from src.ai.tools import GetAnomaliesInput, get_anomalies_impl
from src.data.regions import REGIONS_BY_CODE
from src.data.schema import Product
from src.forecast.engine import ForecastEngine

logger = logging.getLogger(__name__)


class AnomalyExplanation(BaseModel):
    year: int = Field(ge=1900, le=2100)
    explanation: str = Field(
        description=(
            "1-2 sentences explaining what known industry/market events of that "
            "year may explain the unusual YoY change. Cite the magnitude from "
            "the data. Do not make up specific dollar figures or precise dates."
        )
    )


class AnomalyReport(BaseModel):
    region: str
    product: str
    explanations: list[AnomalyExplanation] = Field(min_length=0, max_length=10)


@dataclass(frozen=True)
class AnomalyResult:
    region: str
    product: str
    flagged_years: list[dict]  # raw output of statistical detection
    explanations: list[dict]  # per-year text, parallel to flagged_years
    method: str
    is_mock: bool = False
    note: str | None = None


ANOMALY_SYSTEM_PROMPT: str = """\
You are an oil-and-gas analyst. You are given a region, product, and a list
of statistically flagged anomalous years (z-score on year-over-year % change).

For EACH flagged year, write 1-2 sentences explaining what plausible
industry-wide events of that year (e.g., shale boom, oil price collapse,
COVID demand shock, Hurricane Harvey, OPEC+ cuts) could account for the
direction and rough magnitude of the YoY change. Cite the YoY % from the
data. Do not invent dates or dollar figures beyond what is given.

Output strict JSON matching the requested schema. Do not add years that
are not in the input. Do not omit years from the input.
"""


def explain_anomalies(
    client: GeminiClient,
    df: pd.DataFrame,
    engine: ForecastEngine,
    region_code: str,
    product: str,
    z_threshold: float = 2.5,
) -> AnomalyResult:
    """Run statistical detection then ask Gemini for narrative explanations."""
    region_obj = REGIONS_BY_CODE.get(region_code)
    region_name = region_obj.name if region_obj else region_code
    pretty_product = "crude oil" if product == Product.CRUDE_OIL else "natural gas"

    detection = get_anomalies_impl(
        df,
        engine,
        GetAnomaliesInput(region=region_code, product=product, z_threshold=z_threshold),
    )
    if not detection.ok:
        return AnomalyResult(
            region=region_name,
            product=pretty_product,
            flagged_years=[],
            explanations=[],
            method=f"|z|>={z_threshold} on YoY%",
            note=detection.error,
        )

    payload = detection.data or {}
    flagged: list[dict] = payload.get("anomalies", []) or []
    method = payload.get("method", f"|z|>={z_threshold} on YoY%")

    if not flagged:
        return AnomalyResult(
            region=region_name,
            product=pretty_product,
            flagged_years=[],
            explanations=[],
            method=method,
            note=(
                f"No years exceed |z|>={z_threshold} for {region_name} {pretty_product} "
                f"(mean YoY {payload.get('mean_yoy_pct', 0):.1f}%, "
                f"std YoY {payload.get('std_yoy_pct', 0):.1f}%)."
            ),
        )

    if client.mock or not client.is_available():
        return _fallback_explanations(region_name, pretty_product, flagged, method)

    try:
        resp = client.generate(
            contents=[
                genai_types.Content(
                    role="user",
                    parts=[
                        genai_types.Part(
                            text=(
                                f"Region: {region_name}\n"
                                f"Product: {pretty_product}\n"
                                f"Method: {method}\n"
                                f"Flagged anomalies (statistical detection — do not modify):\n"
                                f"{json.dumps(flagged, indent=2)}"
                            )
                        )
                    ],
                )
            ],
            system_instruction=ANOMALY_SYSTEM_PROMPT,
            response_schema=AnomalyReport,
            response_mime_type="application/json",
        )
    except GeminiUnavailable as e:
        logger.warning("explain_anomalies: Gemini unavailable; using fallback: %s", e)
        return _fallback_explanations(region_name, pretty_product, flagged, method)

    raw_text = (resp.text or "").strip() if hasattr(resp, "text") else ""
    if not raw_text and resp.candidates:
        parts = resp.candidates[0].content.parts if resp.candidates[0].content else []
        raw_text = "".join(getattr(p, "text", "") or "" for p in parts)

    try:
        parsed = AnomalyReport.model_validate_json(raw_text)
    except (ValidationError, ValueError) as e:
        logger.warning("explain_anomalies: parse failed (%s); using fallback", e)
        return _fallback_explanations(region_name, pretty_product, flagged, method)

    # Pair explanations with the flagged-years payload, by year.
    explain_by_year = {x.year: x.explanation for x in parsed.explanations}
    explanations: list[dict] = []
    for f in flagged:
        explanations.append(
            {
                "year": f["year"],
                "yoy_pct": f["yoy_pct"],
                "z_score": f["z_score"],
                "explanation": explain_by_year.get(
                    f["year"],
                    "(No narrative produced for this year — see numeric values.)",
                ),
            }
        )
    return AnomalyResult(
        region=region_name,
        product=pretty_product,
        flagged_years=flagged,
        explanations=explanations,
        method=method,
    )


def _fallback_explanations(
    region: str,
    pretty_product: str,
    flagged: list[dict],
    method: str,
) -> AnomalyResult:
    """Deterministic per-year notes when the LLM is unavailable."""
    explanations: list[dict] = []
    for f in flagged:
        direction = "spike" if f["yoy_pct"] > 0 else "drop"
        explanations.append(
            {
                "year": f["year"],
                "yoy_pct": f["yoy_pct"],
                "z_score": f["z_score"],
                "explanation": (
                    f"{f['year']} shows a {abs(f['yoy_pct']):.1f}% YoY {direction} "
                    f"(z={f['z_score']:.1f}) — see the chart and KPI history for context."
                ),
            }
        )
    return AnomalyResult(
        region=region,
        product=pretty_product,
        flagged_years=flagged,
        explanations=explanations,
        method=method,
        is_mock=True,
    )
