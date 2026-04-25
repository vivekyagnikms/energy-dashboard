"""Investment recommendation engine: ranks regions by a composite opportunity
score, then asks Gemini to narrate the top 5.

Score model (deterministic; the LLM never invents the ranking):

    score = w1 * z(scale)
          + w2 * z(growth_5yr)
          - w3 * z(volatility)
          + w4 * z(recent_acceleration)

where z(...) is a robust z-score (median / MAD), scale is the most recent
full-year production, growth_5yr is 5-year CAGR, volatility is YoY-CV,
and recent_acceleration is YoY-2024 minus 5y-CAGR.

Defaults: w1=1.0 (scale matters), w2=1.5 (growth matters more),
w3=1.0 (penalize boom/bust), w4=0.5 (acceleration as a tie-breaker).

The LLM only narrates the ranked list. It cannot add or remove regions.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from google.genai import types as genai_types
from pydantic import BaseModel, Field, ValidationError

from src.ai.client import GeminiClient, GeminiUnavailable
from src.data.regions import ALL_REGIONS, RegionGroup
from src.forecast.engine import ForecastEngine
from src.kpis.calculators import (
    five_year_cagr,
    volatility,
    yoy_growth_rate,
)

logger = logging.getLogger(__name__)


# ---------- public API ----------


@dataclass(frozen=True)
class OpportunityRow:
    region_code: str
    region_name: str
    score: float
    scale: float | None  # most recent production, native unit
    growth_5yr: float | None  # decimal
    volatility: float | None  # ratio
    acceleration: float | None  # YoY - CAGR


@dataclass(frozen=True)
class Recommendation:
    region_code: str
    region_name: str
    rank: int
    score: float
    headline: str  # 1 sentence
    rationale: str  # 1-3 sentences explaining the score components
    caveats: list[str]


@dataclass(frozen=True)
class RecommendationReport:
    product: str
    year: int
    rows: list[OpportunityRow]  # full ranked list (filtered to producing regions)
    recommendations: list[Recommendation]  # top 5 (or fewer)
    is_mock: bool = False
    method_note: str = ""


class _RecExplanation(BaseModel):
    region_name: str
    headline: str = Field(min_length=10, max_length=200)
    rationale: str = Field(min_length=10, max_length=600)
    caveats: list[str] = Field(default_factory=list, max_length=3)


class _RecResponse(BaseModel):
    """Pydantic model that doubles as the Gemini response_schema."""

    explanations: list[_RecExplanation] = Field(min_length=1, max_length=10)


# ---------- ranking ----------


def _robust_z(series: pd.Series) -> pd.Series:
    """Robust z-score: (x - median) / (1.4826 * MAD). Handles outliers
    better than mean/std for heavy-tailed production distributions."""
    median = series.median()
    mad = float(np.median(np.abs(series - median)))
    if mad == 0:
        return pd.Series(0.0, index=series.index)
    return (series - median) / (1.4826 * mad)


def rank_opportunities(
    df: pd.DataFrame,
    engine: ForecastEngine,
    product: str,
    year: int,
    *,
    weights: tuple[float, float, float, float] = (1.0, 1.5, 1.0, 0.5),
    include_aggregates: bool = False,
    min_scale_pct_of_us: float = 0.005,
) -> list[OpportunityRow]:
    """Score every supported region for opportunity attractiveness.

    Returns rows sorted by score descending. By default only investable
    units (states + Federal Offshore GoM) are considered — national and
    PADDs are aggregates of states, so including them would mix apples
    (sums) and oranges (constituents). Set `include_aggregates=True` to
    include them anyway.

    `min_scale_pct_of_us` filters out tiny producers (e.g. Idaho with 26
    MBBL / year, where +91% CAGR is statistical noise from a near-zero
    base). Default 0.5% of U.S. national keeps the ranking BD-relevant."""
    # Scale threshold: percent of US national production for this product.
    us_last = df[
        (df["region_code"] == "NUS")
        & (df["product"] == product)
        & (df["n_months"] >= 12)
    ]
    if not us_last.empty:
        us_scale = float(us_last.sort_values("year").iloc[-1]["value"])
    else:
        us_scale = 0.0
    min_scale_threshold = us_scale * min_scale_pct_of_us

    rows: list[dict] = []
    for region in ALL_REGIONS:
        if not engine.is_supported(region.code, product):
            continue
        # Skip aggregate regions: a BD analyst doesn't invest in "USA" or
        # "PADD 3" — those are sums of states / Gulf offshore.
        if not include_aggregates and region.group in (
            RegionGroup.NATIONAL,
            RegionGroup.PADD,
        ):
            continue
        # Use the most recent FULL year for scale & accel; the user-facing
        # `year` parameter is for display only.
        history = engine.history(region.code, product)
        if history.empty:
            continue
        last_full = int(history["year"].iloc[-1])
        scale = float(history["value"].iloc[-1])
        # Tiny-base filter: regions producing less than 0.5% of US national
        # have unstable percentage metrics and are not BD-meaningful.
        if min_scale_threshold > 0 and scale < min_scale_threshold:
            continue
        cagr = five_year_cagr(df, region.code, product, last_full)
        vol = volatility(df, region.code, product, last_full)
        yoy = yoy_growth_rate(df, region.code, product, last_full)
        accel = (yoy - cagr) if (yoy is not None and cagr is not None) else None

        rows.append(
            {
                "region_code": region.code,
                "region_name": region.name,
                "scale": scale,
                "growth_5yr": cagr,
                "volatility": vol,
                "acceleration": accel,
            }
        )

    if not rows:
        return []

    raw = pd.DataFrame(rows)
    # Replace None with NaN so robust_z plays well; impute median for missing.
    for col in ("scale", "growth_5yr", "volatility", "acceleration"):
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
        if raw[col].notna().any():
            raw[col] = raw[col].fillna(raw[col].median())
        else:
            raw[col] = 0.0

    z_scale = _robust_z(raw["scale"])
    z_growth = _robust_z(raw["growth_5yr"])
    z_volatility = _robust_z(raw["volatility"])
    z_accel = _robust_z(raw["acceleration"])

    w_scale, w_growth, w_vol, w_accel = weights
    raw["score"] = (
        w_scale * z_scale
        + w_growth * z_growth
        - w_vol * z_volatility
        + w_accel * z_accel
    )
    raw = raw.sort_values("score", ascending=False).reset_index(drop=True)

    return [
        OpportunityRow(
            region_code=str(r["region_code"]),
            region_name=str(r["region_name"]),
            score=float(r["score"]),
            scale=float(r["scale"]) if pd.notna(r["scale"]) else None,
            growth_5yr=float(r["growth_5yr"]) if pd.notna(r["growth_5yr"]) else None,
            volatility=float(r["volatility"]) if pd.notna(r["volatility"]) else None,
            acceleration=(
                float(r["acceleration"]) if pd.notna(r["acceleration"]) else None
            ),
        )
        for _, r in raw.iterrows()
    ]


# ---------- LLM narrative ----------


_RECOMMEND_SYSTEM_PROMPT: str = """\
You are an oil-and-gas investment analyst writing one-line recommendations
for a business-development team.

You are GIVEN a deterministic top-N ranking with each region's scale, 5-year
CAGR, volatility, and recent acceleration. DO NOT change the ranking. DO NOT
invent regions or numbers. For EACH region, write:
- headline: 1 short sentence ("Texas: scale + steady growth + low volatility").
- rationale: 1-3 sentences citing the score components from the data
  (e.g. "5-year CAGR of +X%, lower volatility than peers, accelerating YoY").
  Reference industry context where defensible (shale, OPEC+, demand cycles)
  but do not invent specific dates or dollar figures.
- caveats: 0-3 honest cautions (forecast extrapolation distance, illustrative
  price assumption, partial-year data, low data history, statistical anomaly
  upcoming, etc.).

Output strict JSON matching the requested schema.
"""


def _fallback_explanations(rows: list[OpportunityRow]) -> list[Recommendation]:
    """Deterministic per-row recommendations when Gemini is unavailable."""
    out: list[Recommendation] = []
    for i, r in enumerate(rows, start=1):
        scale = f"{r.scale:,.0f}" if r.scale else "n/a"
        cagr = f"{r.growth_5yr * 100:+.1f}%" if r.growth_5yr is not None else "n/a"
        vol = f"{r.volatility:.2f}" if r.volatility is not None else "n/a"
        accel_pct = (
            f"{r.acceleration * 100:+.1f}%" if r.acceleration is not None else "n/a"
        )
        out.append(
            Recommendation(
                region_code=r.region_code,
                region_name=r.region_name,
                rank=i,
                score=r.score,
                headline=f"{r.region_name}: rank #{i} on the composite score.",
                rationale=(
                    f"Most recent annual production: {scale}. "
                    f"5-year CAGR: {cagr}. Volatility (CV of YoY%): {vol}. "
                    f"Recent acceleration (YoY − CAGR): {accel_pct}."
                ),
                caveats=[
                    "Score is a deterministic linear combination — see "
                    "src/ai/recommend.py for weights.",
                    "Mock-mode response shown — live AI is rate-limited.",
                ],
            )
        )
    return out


def recommend(
    client: GeminiClient,
    df: pd.DataFrame,
    engine: ForecastEngine,
    product: str,
    year: int,
    *,
    top_n: int = 5,
    weights: tuple[float, float, float, float] = (1.0, 1.5, 1.0, 0.5),
) -> RecommendationReport:
    """End-to-end: rank regions, ask Gemini to narrate the top-N. Falls back
    to deterministic narratives on parse failure or unavailability."""
    rows = rank_opportunities(df, engine, product, year, weights=weights)
    method_note = (
        f"Composite score = "
        f"{weights[0]:.1f}·z(scale) + "
        f"{weights[1]:.1f}·z(5yr-CAGR) − "
        f"{weights[2]:.1f}·z(volatility) + "
        f"{weights[3]:.1f}·z(acceleration); "
        f"robust z-score (median/MAD) for outlier resistance."
    )
    if not rows:
        return RecommendationReport(
            product=product,
            year=year,
            rows=[],
            recommendations=[],
            is_mock=False,
            method_note=method_note,
        )
    top = rows[: min(top_n, len(rows))]

    if client.mock or not client.is_available():
        return RecommendationReport(
            product=product,
            year=year,
            rows=rows,
            recommendations=_fallback_explanations(top),
            is_mock=True,
            method_note=method_note,
        )

    payload = {
        "product": product,
        "year": year,
        "top_n": [
            {
                "rank": i,
                "region_name": r.region_name,
                "score": round(r.score, 3),
                "scale": round(r.scale, 1) if r.scale else None,
                "growth_5yr_pct": (
                    round(r.growth_5yr * 100, 2) if r.growth_5yr is not None else None
                ),
                "volatility_cv": (
                    round(r.volatility, 3) if r.volatility is not None else None
                ),
                "acceleration_pct": (
                    round(r.acceleration * 100, 2)
                    if r.acceleration is not None
                    else None
                ),
            }
            for i, r in enumerate(top, start=1)
        ],
    }

    try:
        resp = client.generate(
            contents=[
                genai_types.Content(
                    role="user",
                    parts=[
                        genai_types.Part(
                            text=(
                                "Write recommendation narratives for the "
                                "regions below — DO NOT modify the ranking.\n\n"
                                f"{json.dumps(payload, indent=2)}"
                            )
                        )
                    ],
                )
            ],
            system_instruction=_RECOMMEND_SYSTEM_PROMPT,
            response_schema=_RecResponse,
            response_mime_type="application/json",
        )
    except GeminiUnavailable as e:
        logger.warning("recommend: Gemini unavailable; using fallback: %s", e)
        return RecommendationReport(
            product=product,
            year=year,
            rows=rows,
            recommendations=_fallback_explanations(top),
            is_mock=True,
            method_note=method_note,
        )

    raw_text = (resp.text or "").strip() if hasattr(resp, "text") else ""
    if not raw_text and resp.candidates:
        parts = resp.candidates[0].content.parts if resp.candidates[0].content else []
        raw_text = "".join(getattr(p, "text", "") or "" for p in parts)

    try:
        parsed = _RecResponse.model_validate_json(raw_text)
    except (ValidationError, ValueError) as e:
        logger.warning("recommend: parse failed (%s); using fallback", e)
        return RecommendationReport(
            product=product,
            year=year,
            rows=rows,
            recommendations=_fallback_explanations(top),
            is_mock=True,
            method_note=method_note,
        )

    # Pair LLM explanations to ranked rows by region_name (LLM is told NOT
    # to reorder, but we defensively look up by name anyway).
    by_name = {x.region_name: x for x in parsed.explanations}
    out: list[Recommendation] = []
    for i, r in enumerate(top, start=1):
        explanation = by_name.get(r.region_name)
        if explanation is None:
            # Mismatch — degrade gracefully to deterministic for this row.
            fallback = _fallback_explanations([r])[0]
            out.append(
                Recommendation(
                    region_code=r.region_code,
                    region_name=r.region_name,
                    rank=i,
                    score=r.score,
                    headline=fallback.headline,
                    rationale=fallback.rationale,
                    caveats=fallback.caveats,
                )
            )
        else:
            out.append(
                Recommendation(
                    region_code=r.region_code,
                    region_name=r.region_name,
                    rank=i,
                    score=r.score,
                    headline=explanation.headline,
                    rationale=explanation.rationale,
                    caveats=list(explanation.caveats),
                )
            )

    return RecommendationReport(
        product=product,
        year=year,
        rows=rows,
        recommendations=out,
        is_mock=False,
        method_note=method_note,
    )
