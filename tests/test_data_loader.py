"""Unit tests for the EIA data normalization layer.

These tests do NOT hit the live API; they feed _normalize_rows the kind of
dict payloads EIA actually returns and verify our handling of:
- the MBBL vs MBBL/D crude-oil duplicate (we keep MBBL)
- monthly -> annual aggregation
- partial-year n_months tracking
- unknown duoarea filtering
- missing/zero values
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.data.loader import _normalize_rows
from src.data.schema import Product


def _row(*, period: str, duoarea: str, value: str, units: str = "MBBL") -> dict:
    """Minimal EIA-shape row for tests."""
    return {
        "period": period, "duoarea": duoarea, "value": value, "units": units,
        "product": "EPC0", "process": "FPF",
    }


def test_crude_filter_drops_mbbl_per_day_rows():
    # Two rows for the same (region, period): one in MBBL (kept), one MBBL/D (dropped).
    rows = [
        _row(period="2023-01", duoarea="NUS", value="391000", units="MBBL"),
        _row(period="2023-01", duoarea="NUS", value="12640",  units="MBBL/D"),
    ]
    df = _normalize_rows(rows, Product.CRUDE_OIL)
    assert len(df) == 1
    assert df["unit"].iloc[0] == "MBBL"
    # Value matches the MBBL row only — NOT the sum of both.
    assert df["value"].iloc[0] == 391000


def test_monthly_to_annual_aggregation_sums_within_year():
    rows = [
        _row(period=f"2022-{m:02d}", duoarea="STX", value="100000", units="MBBL")
        for m in range(1, 13)
    ]
    df = _normalize_rows(rows, Product.CRUDE_OIL)
    assert len(df) == 1
    assert df["value"].iloc[0] == 1_200_000
    assert df["n_months"].iloc[0] == 12


def test_partial_year_tracked_in_n_months():
    rows = [
        _row(period=f"2026-{m:02d}", duoarea="STX", value="100000")
        for m in range(1, 4)
    ]
    df = _normalize_rows(rows, Product.CRUDE_OIL)
    assert df["n_months"].iloc[0] == 3
    assert df["value"].iloc[0] == 300_000


def test_unknown_duoarea_filtered_out():
    rows = [
        _row(period="2023-01", duoarea="NUS", value="391000"),
        _row(period="2023-01", duoarea="ZZZ_FAKE", value="999999"),
    ]
    df = _normalize_rows(rows, Product.CRUDE_OIL)
    assert set(df["region_code"]) == {"NUS"}


def test_missing_value_is_dropped():
    rows = [
        _row(period="2023-01", duoarea="NUS", value="100"),
        _row(period="2023-02", duoarea="NUS", value=""),  # missing
        _row(period="2023-03", duoarea="NUS", value="abc"),  # invalid
    ]
    df = _normalize_rows(rows, Product.CRUDE_OIL)
    # Only the 100 survived; n_months=1, value=100.
    assert df["value"].iloc[0] == 100
    assert df["n_months"].iloc[0] == 1


def test_empty_input_returns_empty_typed_dataframe():
    df = _normalize_rows([], Product.NATURAL_GAS)
    assert df.empty
    assert "region_code" in df.columns


def test_natural_gas_uses_mmcf_unit():
    rows = [
        {"period": "2023-01", "duoarea": "STX", "value": "1000",
         "units": "MMCF", "product": "EPG0", "process": "VGM"},
    ]
    df = _normalize_rows(rows, Product.NATURAL_GAS)
    assert df["unit"].iloc[0] == "MMCF"


def test_missing_required_column_raises():
    bad_rows = [{"period": "2023-01", "value": "100", "units": "MBBL"}]  # no duoarea
    with pytest.raises(ValueError, match="missing expected columns"):
        _normalize_rows(bad_rows, Product.CRUDE_OIL)
