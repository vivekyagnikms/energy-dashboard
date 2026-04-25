"""Critical-path tests for KPI calculators.

Coverage: each KPI's happy path + obvious edge cases (zero, missing,
single-year, non-producer). Combined entry point integration."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from src.data.schema import Product
from src.forecast.engine import ForecastEngine
from src.kpis.calculators import (
    CAGR_WINDOW_YEARS,
    HENRY_HUB_USD_PER_MMBTU,
    MMBTU_PER_MMCF,
    WTI_PRICE_USD_PER_BBL,
    compute_kpi_set,
    five_year_cagr,
    get_actual_or_forecast,
    revenue_potential_usd,
    volatility,
    yoy_growth_rate,
)


def _df(values: dict[int, float], *, region: str = "STX", region_name: str = "Texas",
        product: str = Product.CRUDE_OIL, unit: str = "MBBL", n_months: int = 12) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "region_code": region, "region_name": region_name,
            "product": product, "year": y, "value": v, "unit": unit, "n_months": n_months,
        }
        for y, v in values.items()
    ])


# ---------- yoy_growth_rate ----------


def test_yoy_basic():
    df = _df({2020: 100.0, 2021: 110.0})
    assert yoy_growth_rate(df, "STX", Product.CRUDE_OIL, 2021) == pytest.approx(0.10)


def test_yoy_returns_none_when_prior_year_missing():
    df = _df({2021: 110.0})
    assert yoy_growth_rate(df, "STX", Product.CRUDE_OIL, 2021) is None


def test_yoy_returns_none_when_prior_is_zero():
    df = _df({2020: 0.0, 2021: 50.0})
    assert yoy_growth_rate(df, "STX", Product.CRUDE_OIL, 2021) is None


# ---------- five_year_cagr ----------


def test_five_year_cagr_doubling():
    df = _df({2020: 100.0, 2025: 200.0})
    expected = 200.0 ** (1.0 / CAGR_WINDOW_YEARS) / 100.0 ** (1.0 / CAGR_WINDOW_YEARS) - 1.0
    assert five_year_cagr(df, "STX", Product.CRUDE_OIL, 2025) == pytest.approx(expected)


def test_five_year_cagr_returns_none_when_endpoint_missing():
    df = _df({2020: 100.0})
    assert five_year_cagr(df, "STX", Product.CRUDE_OIL, 2025) is None


def test_five_year_cagr_returns_none_when_start_zero():
    df = _df({2020: 0.0, 2025: 100.0})
    assert five_year_cagr(df, "STX", Product.CRUDE_OIL, 2025) is None


# ---------- volatility ----------


def test_volatility_constant_growth_is_zero_or_none():
    # Identical YoY = std 0; mean nonzero -> ratio 0
    df = _df({2015 + i: 100.0 * (1.10 ** i) for i in range(8)})
    v = volatility(df, "STX", Product.CRUDE_OIL, 2022)
    assert v is not None
    assert v == pytest.approx(0.0, abs=1e-9)


def test_volatility_returns_none_when_too_few_observations():
    df = _df({2021: 100.0, 2022: 110.0})
    assert volatility(df, "STX", Product.CRUDE_OIL, 2022) is None


def test_volatility_high_for_noisy_series():
    df = _df({2015: 100, 2016: 50, 2017: 200, 2018: 60, 2019: 180, 2020: 70})
    v = volatility(df, "STX", Product.CRUDE_OIL, 2020)
    assert v is not None
    assert v > 0.5  # noisy series -> high coefficient of variation


# ---------- revenue_potential ----------


def test_revenue_potential_crude_uses_wti():
    df = _df({2020 + i: 1000.0 + 100.0 * i for i in range(6)})
    engine = ForecastEngine(df)
    rev = revenue_potential_usd(df, engine, "STX", Product.CRUDE_OIL, 2025)
    expected_volume = 1500.0  # MBBL
    expected_rev = expected_volume * 1000.0 * WTI_PRICE_USD_PER_BBL
    assert rev == pytest.approx(expected_rev, rel=1e-6)


def test_revenue_potential_gas_uses_henry_hub_with_mmbtu_conversion():
    df = _df({2020 + i: 1000.0 + 50.0 * i for i in range(6)},
             product=Product.NATURAL_GAS, unit="MMCF")
    engine = ForecastEngine(df)
    rev = revenue_potential_usd(df, engine, "STX", Product.NATURAL_GAS, 2025)
    expected_volume = 1250.0  # MMCF
    expected_rev = expected_volume * MMBTU_PER_MMCF * HENRY_HUB_USD_PER_MMBTU
    assert rev == pytest.approx(expected_rev, rel=1e-6)


def test_revenue_potential_none_when_no_data():
    df = _df({2021: 100.0})
    engine = ForecastEngine(df)
    assert revenue_potential_usd(df, engine, "STX", Product.CRUDE_OIL, 2030) is None


# ---------- get_actual_or_forecast ----------


def test_get_actual_or_forecast_uses_actual_for_past():
    df = _df({2020 + i: 100.0 + 10.0 * i for i in range(6)})
    engine = ForecastEngine(df)
    value, is_forecast = get_actual_or_forecast(df, engine, "STX", Product.CRUDE_OIL, 2024)
    assert is_forecast is False
    assert value == pytest.approx(140.0)


def test_get_actual_or_forecast_uses_forecast_for_future():
    df = _df({2020 + i: 100.0 + 10.0 * i for i in range(6)})
    engine = ForecastEngine(df)
    value, is_forecast = get_actual_or_forecast(df, engine, "STX", Product.CRUDE_OIL, 2030)
    assert is_forecast is True
    assert value > 140.0  # extrapolated upward


# ---------- compute_kpi_set ----------


def test_compute_kpi_set_for_known_region():
    # 6 years of full data for a region; year=2024 is in the data.
    df = _df({2019 + i: 100.0 * (1.05 ** i) for i in range(6)})
    engine = ForecastEngine(df)
    kpis = compute_kpi_set(df, engine, "STX", Product.CRUDE_OIL, 2024)
    assert kpis.region_code == "STX"
    assert kpis.is_forecast is False
    assert kpis.projected_production is not None
    assert kpis.yoy_growth_rate == pytest.approx(0.05, rel=1e-3)
    assert kpis.revenue_potential_usd is not None
    assert kpis.notes == []


def test_compute_kpi_set_for_non_producer_returns_clean_empty_state():
    # Region with NO data at all
    df = pd.DataFrame(
        columns=["region_code", "region_name", "product", "year", "value", "unit", "n_months"]
    )
    engine = ForecastEngine(_df({2020 + i: 100.0 for i in range(6)}))  # supply some other data so engine works
    kpis = compute_kpi_set(df, engine, "SVT", "crude_oil", 2024)
    assert kpis.projected_production is None
    assert kpis.yoy_growth_rate is None
    assert kpis.revenue_potential_usd is None
    assert any("does not have meaningful" in n for n in kpis.notes)


def test_compute_kpi_set_future_year_marks_is_forecast():
    df = _df({2019 + i: 100.0 + 10.0 * i for i in range(6)})
    engine = ForecastEngine(df)
    kpis = compute_kpi_set(df, engine, "STX", Product.CRUDE_OIL, 2030)
    assert kpis.is_forecast is True
    assert kpis.projected_production is not None
    assert math.isfinite(kpis.projected_production)
