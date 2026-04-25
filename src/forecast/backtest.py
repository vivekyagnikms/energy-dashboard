"""Forecast backtesting: how good is the linear model on data we already have?

Walk-forward evaluation: for each holdout year Y, train on history up to
year Y-1, predict Y, compare to actual. Aggregate into per-region MAPE
(mean absolute percent error) and bias.

This is what proves the forecast is calibrated, not just a line on a chart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

# Don't backtest a region with fewer than this many training years available.
_MIN_TRAIN_YEARS: Final[int] = 5
# Skip years where the actual is too small (relative MAPE explodes otherwise).
_MIN_ACTUAL_FOR_MAPE: Final[float] = 1.0


@dataclass(frozen=True)
class BacktestResult:
    """Per-region backtest summary."""

    region_code: str
    region_name: str
    product: str
    n_holdout_years: int
    mape_pct: float | None  # mean absolute percent error
    bias_pct: float | None  # mean signed % error (>0 = forecast tends high)
    r_squared_avg: float | None  # avg training R² across walk-forward fits
    rows: pd.DataFrame  # one row per holdout year: year, actual, predicted, error_pct


def backtest_region(
    df: pd.DataFrame,
    region_code: str,
    product: str,
) -> BacktestResult | None:
    """Walk-forward backtest for one (region, product). Returns None if there
    is not enough history to backtest at all."""
    mask = (
        (df["region_code"] == region_code)
        & (df["product"] == product)
        & (df["n_months"] >= 12)
    )
    series = df.loc[mask, ["year", "value"]].sort_values("year").reset_index(drop=True)
    if len(series) < _MIN_TRAIN_YEARS + 1:
        return None

    region_name_match = df.loc[df["region_code"] == region_code, "region_name"]
    region_name = (
        str(region_name_match.iloc[0]) if not region_name_match.empty else region_code
    )

    rows: list[dict] = []
    r2s: list[float] = []
    for i in range(_MIN_TRAIN_YEARS, len(series)):
        train = series.iloc[:i]
        test_year = int(series["year"].iloc[i])
        actual = float(series["value"].iloc[i])

        x = train["year"].to_numpy().reshape(-1, 1)
        y = train["value"].to_numpy()
        model = LinearRegression().fit(x, y)
        predicted = float(model.predict(np.array([[test_year]]))[0])
        r2s.append(float(model.score(x, y)))

        if actual >= _MIN_ACTUAL_FOR_MAPE:
            err_pct = (predicted - actual) / actual * 100.0
        else:
            err_pct = float("nan")

        rows.append(
            {
                "year": test_year,
                "actual": actual,
                "predicted": predicted,
                "error_pct": err_pct,
                "abs_error_pct": abs(err_pct),
            }
        )

    rows_df = pd.DataFrame(rows)
    finite_mask = rows_df["abs_error_pct"].notna()
    valid = rows_df[finite_mask]

    return BacktestResult(
        region_code=region_code,
        region_name=region_name,
        product=product,
        n_holdout_years=len(rows_df),
        mape_pct=float(valid["abs_error_pct"].mean()) if not valid.empty else None,
        bias_pct=float(valid["error_pct"].mean()) if not valid.empty else None,
        r_squared_avg=float(np.mean(r2s)) if r2s else None,
        rows=rows_df,
    )


def backtest_all_regions(
    df: pd.DataFrame, product: str, *, min_holdout_years: int = 3
) -> pd.DataFrame:
    """Backtest every region with at least `min_holdout_years` of holdout data
    for the given product. Returns a DataFrame ranked ascending by MAPE
    (best-calibrated regions first)."""
    out: list[dict] = []
    for region_code in df["region_code"].unique():
        result = backtest_region(df, str(region_code), product)
        if result is None:
            continue
        if result.n_holdout_years < min_holdout_years:
            continue
        if result.mape_pct is None:
            continue
        out.append(
            {
                "region_code": result.region_code,
                "region_name": result.region_name,
                "product": product,
                "n_holdout_years": result.n_holdout_years,
                "mape_pct": result.mape_pct,
                "bias_pct": result.bias_pct,
                "r_squared_avg": result.r_squared_avg,
            }
        )
    if not out:
        return pd.DataFrame(
            columns=[
                "region_code",
                "region_name",
                "product",
                "n_holdout_years",
                "mape_pct",
                "bias_pct",
                "r_squared_avg",
            ]
        )
    return pd.DataFrame(out).sort_values("mape_pct").reset_index(drop=True)
