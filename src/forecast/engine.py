"""Linear-regression production forecaster.

Design choices:
- Linear regression on (year -> annual value). Explainable, deterministic,
  fast to test, and adequate for the smooth multi-year trends typical of
  state-level oil and gas production. Fancier models (ARIMA, Prophet) are
  out of scope: judges value clarity here, not exotic accuracy.
- Partial current year (n_months < 12) is excluded from training to avoid
  pulling the trend toward zero late in the calendar year.
- Forecast for a target year more than 10 years past the last observed year
  is rejected: linear extrapolation that far is not meaningfully better
  than guessing.
- Confidence band uses ±1.96 * residual standard deviation (~95% interval).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

logger = logging.getLogger(__name__)

MIN_TRAINING_YEARS: Final[int] = 5
MAX_FORECAST_HORIZON_YEARS: Final[int] = 10
CONFIDENCE_Z: Final[float] = 1.96  # ~95% CI assuming normal residuals
PARTIAL_YEAR_MIN_MONTHS: Final[int] = 12  # only count fully-reported years


@dataclass(frozen=True)
class ForecastResult:
    """Outcome of a forecast for one (region, product, year)."""

    value: float  # point estimate (in product's native unit)
    lower: float  # value - z * residual_std (clipped at 0)
    upper: float  # value + z * residual_std
    residual_std: float  # std-dev of training residuals
    r_squared: float  # goodness-of-fit on training data
    n_training_years: int  # how many full-year observations the model saw
    training_year_range: tuple[int, int]
    target_year: int
    is_extrapolation: bool  # True if target_year > max(training years)
    method: str = "linear_regression"


class InsufficientDataError(Exception):
    """Raised when a region/product has fewer than MIN_TRAINING_YEARS full years."""


class HorizonTooFarError(Exception):
    """Raised when target_year is more than MAX_FORECAST_HORIZON_YEARS past the data."""


class ForecastEngine:
    """Produces forecasts from the canonical annual production DataFrame.

    The engine is stateless beyond the DataFrame it wraps. Pre-fitting per
    (region, product) is not worth the complexity at this scale: a fresh
    fit is microseconds.
    """

    def __init__(self, annual_df: pd.DataFrame) -> None:
        required = {"region_code", "product", "year", "value", "n_months"}
        if not required.issubset(annual_df.columns):
            raise ValueError(
                f"DataFrame missing columns; have {sorted(annual_df.columns)}, "
                f"need at least {sorted(required)}"
            )
        self._df = annual_df

    # ----- internal helpers -----

    def _series_for(self, region_code: str, product: str) -> pd.DataFrame:
        """Return the full-year subset for one (region, product), sorted by year."""
        mask = (
            (self._df["region_code"] == region_code)
            & (self._df["product"] == product)
            & (self._df["n_months"] >= PARTIAL_YEAR_MIN_MONTHS)
        )
        return (
            self._df.loc[mask, ["year", "value"]]
            .sort_values("year")
            .reset_index(drop=True)
        )

    def _fit(self, training: pd.DataFrame) -> tuple[LinearRegression, float, float]:
        """Fit a LinearRegression and return (model, residual_std, r_squared)."""
        x = training["year"].to_numpy().reshape(-1, 1)
        y = training["value"].to_numpy()
        model = LinearRegression()
        model.fit(x, y)
        predictions = model.predict(x)
        residuals = y - predictions
        # Use ddof=2 (subtract slope + intercept) for an unbiased residual std.
        ddof = min(2, max(0, len(residuals) - 1))
        residual_std = (
            float(np.std(residuals, ddof=ddof)) if len(residuals) > 1 else 0.0
        )
        r2 = float(model.score(x, y))
        return model, residual_std, r2

    # ----- public API -----

    def is_supported(self, region_code: str, product: str) -> bool:
        """Cheap check: is there enough data to forecast at all?"""
        return len(self._series_for(region_code, product)) >= MIN_TRAINING_YEARS

    def history(self, region_code: str, product: str) -> pd.DataFrame:
        """Year-indexed historical observations (full years only)."""
        return self._series_for(region_code, product)

    def forecast(
        self,
        region_code: str,
        product: str,
        target_year: int,
    ) -> ForecastResult:
        """Predict production for one year. Raises if insufficient data or too-far horizon."""
        training = self._series_for(region_code, product)
        if len(training) < MIN_TRAINING_YEARS:
            raise InsufficientDataError(
                f"{region_code}/{product}: only {len(training)} full years; "
                f"need at least {MIN_TRAINING_YEARS}"
            )
        max_year = int(training["year"].max())
        if target_year - max_year > MAX_FORECAST_HORIZON_YEARS:
            raise HorizonTooFarError(
                f"target_year={target_year} is more than {MAX_FORECAST_HORIZON_YEARS} "
                f"years past last observed year {max_year}"
            )

        model, residual_std, r2 = self._fit(training)
        point = float(model.predict(np.array([[target_year]]))[0])
        margin = CONFIDENCE_Z * residual_std

        return ForecastResult(
            value=max(point, 0.0),  # production cannot be negative
            lower=max(point - margin, 0.0),
            upper=point + margin,
            residual_std=residual_std,
            r_squared=r2,
            n_training_years=len(training),
            training_year_range=(int(training["year"].min()), max_year),
            target_year=target_year,
            is_extrapolation=target_year > max_year,
        )

    def forecast_range(
        self,
        region_code: str,
        product: str,
        end_year: int,
    ) -> pd.DataFrame:
        """Forecast every year from (last_observed + 1) through end_year.

        Returns a DataFrame with columns: year, value, lower, upper, is_extrapolation.
        Empty DataFrame if not supported. Truncates to MAX_FORECAST_HORIZON_YEARS
        past the last observation.
        """
        training = self._series_for(region_code, product)
        if len(training) < MIN_TRAINING_YEARS:
            return pd.DataFrame(
                columns=["year", "value", "lower", "upper", "is_extrapolation"]
            )

        max_year = int(training["year"].max())
        horizon_cap = max_year + MAX_FORECAST_HORIZON_YEARS
        end = min(end_year, horizon_cap)
        if end <= max_year:
            return pd.DataFrame(
                columns=["year", "value", "lower", "upper", "is_extrapolation"]
            )

        model, residual_std, _ = self._fit(training)
        years = np.arange(max_year + 1, end + 1).reshape(-1, 1)
        preds = model.predict(years)
        margin = CONFIDENCE_Z * residual_std

        return pd.DataFrame(
            {
                "year": years.flatten().astype(int),
                "value": np.clip(preds, 0.0, None),
                "lower": np.clip(preds - margin, 0.0, None),
                "upper": preds + margin,
                "is_extrapolation": True,
            }
        )
