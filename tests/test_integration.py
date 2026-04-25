"""End-to-end pipeline integration tests (no live API).

Feeds recorded EIA-shape rows through the full pipeline:
    raw rows -> normalize -> ForecastEngine -> compute_kpi_set
and checks the KPI bundle is internally consistent.
"""
from __future__ import annotations

import pandas as pd

from src.data.loader import _normalize_rows
from src.data.schema import Product
from src.forecast.engine import ForecastEngine
from src.kpis.calculators import compute_kpi_set


def _monthly_rows(year: int, area: str, monthly_value: float, units: str = "MBBL") -> list[dict]:
    return [
        {"period": f"{year}-{m:02d}", "duoarea": area, "value": str(monthly_value),
         "units": units, "product": "EPC0", "process": "FPF"}
        for m in range(1, 13)
    ]


def test_full_pipeline_normalize_forecast_kpis():
    # Simulate 8 years of growing crude production for Texas.
    raw: list[dict] = []
    for i in range(8):
        # Monthly values grow each year so the annual total grows linearly.
        raw.extend(_monthly_rows(2017 + i, "STX", 100_000 + i * 1_000))

    df = _normalize_rows(raw, Product.CRUDE_OIL)
    assert not df.empty
    assert df["region_code"].iloc[0] == "STX"
    assert df["unit"].iloc[0] == "MBBL"

    # Each year should sum to monthly_value * 12
    expected_2024 = (100_000 + 7 * 1_000) * 12
    assert int(df.loc[df["year"] == 2024, "value"].iloc[0]) == expected_2024

    engine = ForecastEngine(df)
    assert engine.is_supported("STX", Product.CRUDE_OIL)

    # KPI bundle for the last full year (2024).
    kpis = compute_kpi_set(df, engine, "STX", Product.CRUDE_OIL, 2024)
    assert kpis.projected_production == expected_2024
    assert kpis.is_forecast is False
    assert kpis.yoy_growth_rate is not None
    # YoY: ((100k+7k)*12 - (100k+6k)*12) / ((100k+6k)*12) ≈ 1k/106k ≈ 0.94%
    assert 0.005 < kpis.yoy_growth_rate < 0.015
    assert kpis.revenue_potential_usd is not None and kpis.revenue_potential_usd > 0


def test_pipeline_partial_year_excluded_from_forecast():
    raw: list[dict] = []
    for i in range(7):
        raw.extend(_monthly_rows(2017 + i, "STX", 100_000))
    # 2024 only has 3 months reported.
    raw.extend([
        {"period": f"2024-{m:02d}", "duoarea": "STX", "value": "100000",
         "units": "MBBL", "product": "EPC0", "process": "FPF"}
        for m in range(1, 4)
    ])

    df = _normalize_rows(raw, Product.CRUDE_OIL)
    engine = ForecastEngine(df)

    # Forecast for 2025 should ignore 2024 (n_months=3) when training.
    result = engine.forecast("STX", Product.CRUDE_OIL, 2025)
    # Training years should be 2017..2023 (7 years).
    assert result.training_year_range == (2017, 2023)
    assert result.n_training_years == 7


def test_pipeline_unknown_region_silently_filtered():
    raw = _monthly_rows(2020, "STX", 1000) + _monthly_rows(2020, "ZZZ_FAKE", 9999)
    df = _normalize_rows(raw, Product.CRUDE_OIL)
    assert "ZZZ_FAKE" not in df["region_code"].unique()
    assert "STX" in df["region_code"].unique()
