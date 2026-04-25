"""Critical-path tests for the forecasting engine.

Coverage targets:
- known linear input -> known forecast
- insufficient data raises
- partial current year is excluded from training
- horizon-too-far raises
- forecast_range matches per-year forecast on every year
- production-cannot-be-negative invariant
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.forecast.engine import (
    HorizonTooFarError,
    InsufficientDataError,
    ForecastEngine,
    MAX_FORECAST_HORIZON_YEARS,
    MIN_TRAINING_YEARS,
)


def _make_df(
    values_by_year: dict[int, float],
    *,
    n_months: int = 12,
    region_code: str = "STX",
    product: str = "crude_oil",
) -> pd.DataFrame:
    """Build a minimal DataFrame matching the canonical schema."""
    return pd.DataFrame(
        [
            {
                "region_code": region_code,
                "region_name": "Texas",
                "product": product,
                "year": y,
                "value": v,
                "unit": "MBBL",
                "n_months": n_months,
            }
            for y, v in values_by_year.items()
        ]
    )


def test_perfect_linear_input_recovers_exact_forecast():
    # y = 100 + 10*(year - 2010) for years 2010..2019  -> slope 10, intercept 100
    df = _make_df({2010 + i: 100.0 + 10.0 * i for i in range(10)})
    engine = ForecastEngine(df)
    result = engine.forecast("STX", "crude_oil", 2025)
    assert result.value == pytest.approx(100.0 + 10.0 * 15, rel=1e-6)
    assert result.r_squared == pytest.approx(1.0, abs=1e-9)
    assert result.residual_std == pytest.approx(0.0, abs=1e-6)
    assert result.is_extrapolation is True


def test_insufficient_data_raises():
    df = _make_df({2020 + i: 100.0 for i in range(MIN_TRAINING_YEARS - 1)})
    engine = ForecastEngine(df)
    with pytest.raises(InsufficientDataError):
        engine.forecast("STX", "crude_oil", 2030)


def test_partial_current_year_is_excluded_from_training():
    # 5 full years (n_months=12) from 2020..2024 with stable value 100,
    # plus a partial 2025 (n_months=4) with very low value 30.
    full = _make_df({2020 + i: 100.0 for i in range(5)}, n_months=12)
    partial = _make_df({2025: 30.0}, n_months=4)
    df = pd.concat([full, partial], ignore_index=True)
    engine = ForecastEngine(df)
    # If partial were included it would tilt the slope sharply downward.
    result = engine.forecast("STX", "crude_oil", 2026)
    assert result.value == pytest.approx(100.0, rel=1e-6)
    assert result.n_training_years == 5


def test_horizon_too_far_raises():
    df = _make_df({2010 + i: 100.0 + i for i in range(10)})
    engine = ForecastEngine(df)
    last_year = 2019
    with pytest.raises(HorizonTooFarError):
        engine.forecast("STX", "crude_oil", last_year + MAX_FORECAST_HORIZON_YEARS + 1)


def test_forecast_value_is_clipped_at_zero():
    # Steeply declining series whose linear extrapolation would go negative.
    df = _make_df({2010 + i: 1000.0 - 200.0 * i for i in range(6)})
    engine = ForecastEngine(df)
    far_year = 2017  # well past the zero-crossing
    result = engine.forecast("STX", "crude_oil", far_year)
    assert result.value >= 0.0
    assert result.lower >= 0.0


def test_forecast_range_agrees_with_per_year_calls():
    df = _make_df({2010 + i: 100.0 + 5.0 * i + (i % 3) for i in range(10)})
    engine = ForecastEngine(df)
    fr = engine.forecast_range("STX", "crude_oil", 2025)
    assert not fr.empty
    for _, row in fr.iterrows():
        single = engine.forecast("STX", "crude_oil", int(row["year"]))
        assert single.value == pytest.approx(row["value"])
        assert single.lower == pytest.approx(row["lower"])


def test_forecast_range_truncates_to_horizon_cap():
    df = _make_df({2010 + i: 100.0 + i for i in range(10)})
    engine = ForecastEngine(df)
    fr = engine.forecast_range("STX", "crude_oil", end_year=2100)
    last_observed = 2019
    assert int(fr["year"].max()) == last_observed + MAX_FORECAST_HORIZON_YEARS


def test_is_supported_reflects_full_year_count():
    full = _make_df({2020 + i: 100.0 for i in range(MIN_TRAINING_YEARS)}, n_months=12)
    engine = ForecastEngine(full)
    assert engine.is_supported("STX", "crude_oil") is True
    assert (
        engine.is_supported("STX", "natural_gas") is False
    )  # no data for that product
    assert engine.is_supported("UNKNOWN", "crude_oil") is False


def test_history_returns_only_full_years_sorted():
    full = _make_df({2022: 100.0, 2020: 80.0, 2021: 90.0}, n_months=12)
    partial = _make_df({2023: 25.0}, n_months=6)
    df = pd.concat([full, partial], ignore_index=True)
    engine = ForecastEngine(df)
    hist = engine.history("STX", "crude_oil")
    assert list(hist["year"]) == [2020, 2021, 2022]
    assert list(hist["value"]) == [80.0, 90.0, 100.0]
