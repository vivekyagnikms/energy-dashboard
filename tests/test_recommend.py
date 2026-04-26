"""Tests for the investment-recommendation engine.

Pure-Python ranking is testable without Gemini; the LLM-narration path is
exercised via the mock client (deterministic fallback)."""

from __future__ import annotations

import pandas as pd

from src.ai.client import GeminiClient
from src.ai.recommend import (
    OpportunityRow,
    rank_opportunities,
    recommend,
)
from src.data.schema import Product
from src.forecast.engine import ForecastEngine


def _multi_region_df(
    scale_by_region: dict[str, float], *, years: int = 10
) -> pd.DataFrame:
    """Build a dataframe with linear growth for multiple regions."""
    rows = []
    region_codes = {
        "Texas": "STX",
        "New Mexico": "SNM",
        "North Dakota": "SND",
        "Oklahoma": "SOK",
        "Vermont": "SVT",
        "United States": "NUS",
    }
    for region_name, base_scale in scale_by_region.items():
        code = region_codes.get(region_name, region_name[:3].upper())
        for i in range(years):
            rows.append(
                {
                    "region_code": code,
                    "region_name": region_name,
                    "product": Product.CRUDE_OIL,
                    "year": 2014 + i,
                    "value": base_scale * (1.0 + 0.05 * i),
                    "unit": "MBBL",
                    "n_months": 12,
                }
            )
    return pd.DataFrame(rows)


def test_ranking_excludes_aggregates_by_default():
    df = _multi_region_df(
        {
            "Texas": 1_000_000,
            "New Mexico": 500_000,
            "United States": 4_000_000,  # aggregate; should be excluded
        }
    )
    engine = ForecastEngine(df)
    rows = rank_opportunities(df, engine, Product.CRUDE_OIL, 2024)
    region_names = {r.region_name for r in rows}
    assert "United States" not in region_names
    assert "Texas" in region_names


def test_ranking_filters_tiny_producers():
    df = _multi_region_df(
        {
            "Texas": 1_000_000,
            "Vermont": 5,  # tiny — should be filtered
            "United States": 1_500_000,  # used to compute the threshold
        }
    )
    engine = ForecastEngine(df)
    rows = rank_opportunities(df, engine, Product.CRUDE_OIL, 2024)
    region_names = {r.region_name for r in rows}
    assert "Vermont" not in region_names
    assert "Texas" in region_names


def test_ranking_returns_descending_score():
    df = _multi_region_df(
        {
            "Texas": 1_000_000,
            "New Mexico": 500_000,
            "North Dakota": 300_000,
            "Oklahoma": 200_000,
            "United States": 3_000_000,
        }
    )
    engine = ForecastEngine(df)
    rows = rank_opportunities(df, engine, Product.CRUDE_OIL, 2024)
    scores = [r.score for r in rows]
    assert scores == sorted(scores, reverse=True)


def test_recommend_falls_back_to_deterministic_in_mock_mode():
    df = _multi_region_df(
        {
            "Texas": 1_000_000,
            "New Mexico": 500_000,
            "North Dakota": 300_000,
            "United States": 2_000_000,
        }
    )
    engine = ForecastEngine(df)
    mock_client = GeminiClient(api_key=None, mock=True)
    report = recommend(mock_client, df, engine, Product.CRUDE_OIL, 2024, top_n=3)
    assert report.is_mock is True
    assert len(report.recommendations) == 3
    # Recommendations must reference real region names from the input.
    names_in_recs = {rec.region_name for rec in report.recommendations}
    names_in_rows = {r.region_name for r in report.rows}
    assert names_in_recs.issubset(names_in_rows)


def test_recommend_caveats_mention_mock_in_fallback():
    df = _multi_region_df(
        {"Texas": 1_000_000, "New Mexico": 500_000, "United States": 2_000_000}
    )
    engine = ForecastEngine(df)
    mock_client = GeminiClient(api_key=None, mock=True)
    report = recommend(mock_client, df, engine, Product.CRUDE_OIL, 2024)
    assert any(
        any("mock" in c.lower() or "rate" in c.lower() for c in rec.caveats)
        for rec in report.recommendations
    )


def test_recommend_method_note_documents_weights():
    df = _multi_region_df(
        {"Texas": 1_000_000, "New Mexico": 500_000, "United States": 2_000_000}
    )
    engine = ForecastEngine(df)
    mock_client = GeminiClient(api_key=None, mock=True)
    report = recommend(mock_client, df, engine, Product.CRUDE_OIL, 2024)
    assert "z(scale)" in report.method_note
    assert "CAGR" in report.method_note


def test_opportunity_row_carries_score_components():
    df = _multi_region_df(
        {"Texas": 1_000_000, "New Mexico": 500_000, "United States": 2_000_000}
    )
    engine = ForecastEngine(df)
    rows = rank_opportunities(df, engine, Product.CRUDE_OIL, 2024)
    assert all(isinstance(r, OpportunityRow) for r in rows)
    assert all(r.scale is not None for r in rows)
    assert all(r.growth_5yr is not None for r in rows)
