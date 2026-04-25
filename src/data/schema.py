"""Typed schemas for production data records and validated DataFrame shape.

Pydantic for individual record validation (used at API ingestion boundary).
Plain typing for the canonical DataFrame columns the rest of the app consumes.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, Field, field_validator


class Product(str):
    """Product identifiers used throughout the app."""

    CRUDE_OIL: Final[str] = "crude_oil"
    NATURAL_GAS: Final[str] = "natural_gas"


PRODUCTS: Final[tuple[str, ...]] = (Product.CRUDE_OIL, Product.NATURAL_GAS)


class ProductionRecord(BaseModel):
    """Single production observation. Validates one EIA API row before it
    enters the canonical DataFrame.
    """

    region_code: str = Field(
        min_length=2, max_length=10, description="EIA duoarea code"
    )
    product: str = Field(description="One of: crude_oil, natural_gas")
    period: str = Field(description="ISO year or year-month, e.g. '2022' or '2022-06'")
    value: float = Field(ge=0, description="Production volume; non-negative")
    unit: str = Field(description="EIA-reported unit, e.g. 'MBBL', 'MMCF'")

    @field_validator("product")
    @classmethod
    def _product_known(cls, v: str) -> str:
        if v not in PRODUCTS:
            raise ValueError(f"unknown product: {v!r}; expected one of {PRODUCTS}")
        return v


# --- Canonical DataFrame schema ---
# After ingestion + normalization the rest of the app expects a DataFrame with
# these columns, indexed by (region_code, product, year). Centralized so the
# loader, forecaster, KPI calculators, and AI tools all agree.
ANNUAL_COLUMNS: Final[tuple[str, ...]] = (
    "region_code",  # EIA duoarea code
    "region_name",  # human-readable
    "product",  # crude_oil | natural_gas
    "year",  # int
    "value",  # float; sum of monthly values for that year
    "unit",  # string; copied through from EIA
    "n_months",  # int; count of months that contributed (12 = full year, <12 = partial)
)


# --- Units we standardize to in the UI ---
# EIA returns crude in MBBL (thousand barrels), gas in MMCF (million cubic feet).
# We keep these native units for accuracy and label them clearly in the UI.
UNIT_LABELS: Final[dict[str, str]] = {
    "MBBL": "thousand barrels",
    "MMcf": "million cubic feet",
    "MMCF": "million cubic feet",
}
