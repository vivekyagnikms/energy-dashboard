"""Tests for the walk-forward backtester."""
from __future__ import annotations

import pandas as pd

from src.data.schema import Product
from src.forecast.backtest import (
    backtest_all_regions,
    backtest_region,
)


def _df(values: dict[int, float], *, region: str = "STX",
        region_name: str = "Texas", product: str = Product.CRUDE_OIL,
        n_months: int = 12) -> pd.DataFrame:
    return pd.DataFrame([
        {"region_code": region, "region_name": region_name,
         "product": product, "year": y, "value": v,
         "unit": "MBBL", "n_months": n_months}
        for y, v in values.items()
    ])


def test_perfect_linear_input_has_near_zero_mape():
    df = _df({2010 + i: 100.0 + 10.0 * i for i in range(12)})
    result = backtest_region(df, "STX", Product.CRUDE_OIL)
    assert result is not None
    assert result.mape_pct < 1.0  # essentially perfect for a perfectly linear series
    assert result.n_holdout_years == 12 - 5  # 7 holdouts (years 6 onwards)


def test_returns_none_for_too_little_history():
    df = _df({2020 + i: 100.0 for i in range(4)})  # only 4 full years
    result = backtest_region(df, "STX", Product.CRUDE_OIL)
    assert result is None


def test_partial_years_excluded_from_backtest():
    full = _df({2015 + i: 100.0 + 10.0 * i for i in range(8)}, n_months=12)
    partial = _df({2023: 1.0}, n_months=3)  # partial year — should be ignored
    df = pd.concat([full, partial], ignore_index=True)
    result = backtest_region(df, "STX", Product.CRUDE_OIL)
    assert result is not None
    # Holdouts are 2020-2022 (3 years; we have 8 full years; min training = 5).
    assert result.n_holdout_years == 3


def test_backtest_all_regions_sorts_by_mape():
    # Region A: perfectly linear (low MAPE).
    a = _df(
        {2010 + i: 100.0 + 10.0 * i for i in range(12)},
        region="STX", region_name="Texas",
    )
    # Region B: noisy, will have higher MAPE.
    b = _df(
        {2010 + i: 100.0 + (10.0 * i if i % 2 == 0 else -10.0 * i) for i in range(12)},
        region="SND", region_name="North Dakota",
    )
    df = pd.concat([a, b], ignore_index=True)
    out = backtest_all_regions(df, Product.CRUDE_OIL)
    assert not out.empty
    # Texas (perfectly linear) should be ahead of North Dakota (noisy).
    assert out.iloc[0]["region_name"] == "Texas"
    assert out.iloc[0]["mape_pct"] < out.iloc[1]["mape_pct"]


def test_backtest_returns_per_year_rows_with_actual_and_predicted():
    df = _df({2010 + i: 100.0 + 10.0 * i for i in range(10)})
    result = backtest_region(df, "STX", Product.CRUDE_OIL)
    assert result is not None
    assert {"year", "actual", "predicted", "error_pct"}.issubset(result.rows.columns)
    assert len(result.rows) == result.n_holdout_years
