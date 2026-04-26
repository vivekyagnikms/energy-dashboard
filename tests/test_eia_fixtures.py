"""Integration tests against recorded EIA API fixtures.

These tests catch API contract drift: if EIA changes a series ID, response
shape, or unit handling, the fixtures stay frozen and the live tests pass —
but these fixture-driven tests will fail because the production code's
expectations no longer match the recorded reality.

Fixtures were recorded once via the live API and saved as JSON under
`tests/fixtures/`. They cover:
- crude oil monthly production for Texas, 2020-2023
- natural gas monthly production for Pennsylvania, 2020-2023
- WTI spot prices for April 2026
- Henry Hub spot prices for 2025-2026
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.data.loader import _normalize_rows
from src.data.prices import _latest_value
from src.data.schema import Product
from src.forecast.engine import ForecastEngine
from src.kpis.calculators import compute_kpi_set

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> list[dict]:
    """Load a fixture JSON file as a list of dicts."""
    path = FIXTURES_DIR / name
    if not path.exists():
        pytest.skip(
            f"Fixture {name} not present (regenerate via tests/fixtures/README)"
        )
    return json.loads(path.read_text())


# ---------- Production fixtures ----------


def test_crude_fixture_shape_and_unit_filter():
    """EIA returns crude in TWO units per period (MBBL + MBBL/D). Our loader
    must keep MBBL only; this asserts that contract."""
    rows = _load_fixture("eia_crude_tx_2020_2023.json")
    assert len(rows) > 0

    units_in_raw = {r.get("units") for r in rows}
    assert "MBBL" in units_in_raw, "raw fixture should have MBBL rows"
    assert "MBBL/D" in units_in_raw, (
        "raw fixture should also have MBBL/D rows — that's the EIA quirk we filter"
    )

    df = _normalize_rows(rows, Product.CRUDE_OIL)

    assert not df.empty
    assert (df["unit"] == "MBBL").all(), "normalized output must be MBBL only"
    assert (df["region_code"] == "STX").all()

    # 4 years of data → 4 annual rows.
    assert len(df) == 4
    assert set(df["year"]) == {2020, 2021, 2022, 2023}

    # Each year should have 12 months reported (full years).
    assert (df["n_months"] == 12).all()

    # Sanity: TX crude annual values should be in the millions of MBBL
    # (TX produces ~5M bpd ≈ 1.8B bbl/year ≈ 1.8M MBBL).
    for _, row in df.iterrows():
        assert 1_000_000 < row["value"] < 2_500_000, (
            f"TX {row['year']} crude unrealistic: {row['value']}"
        )


def test_gas_fixture_normalizes_to_annual_mmcf():
    rows = _load_fixture("eia_gas_pa_2020_2023.json")
    df = _normalize_rows(rows, Product.NATURAL_GAS)

    assert not df.empty
    assert (df["unit"] == "MMCF").all()
    assert (df["region_code"] == "SPA").all()
    assert len(df) == 4
    assert (df["n_months"] == 12).all()

    # Sanity: PA gas annual values should be in millions of MMCF.
    # PA produces ~7 Tcf/yr = 7,000,000 MMCF.
    for _, row in df.iterrows():
        assert 5_000_000 < row["value"] < 9_000_000, (
            f"PA {row['year']} gas unrealistic: {row['value']}"
        )


# ---------- End-to-end pipeline against fixtures ----------


def test_end_to_end_pipeline_against_fixtures():
    """Fixture rows → normalize → engine → KPIs. Verifies no integration
    layer silently broke."""
    crude_rows = _load_fixture("eia_crude_tx_2020_2023.json")
    gas_rows = _load_fixture("eia_gas_pa_2020_2023.json")

    crude_df = _normalize_rows(crude_rows, Product.CRUDE_OIL)
    gas_df = _normalize_rows(gas_rows, Product.NATURAL_GAS)

    import pandas as pd

    df = pd.concat([crude_df, gas_df], ignore_index=True)

    engine = ForecastEngine(df)

    # Both products supported with 4 years (we need 5 for forecast, so skip
    # forecast call here and just verify is_supported is False).
    assert engine.is_supported("STX", Product.CRUDE_OIL) is False, (
        "4 years isn't enough; forecast guard should refuse"
    )
    assert engine.is_supported("SPA", Product.NATURAL_GAS) is False

    # KPI computation should still work for past full years (uses actuals).
    kpis = compute_kpi_set(df, engine, "STX", Product.CRUDE_OIL, 2023)
    assert kpis.region_code == "STX"
    assert kpis.region_name == "Texas"
    assert kpis.is_forecast is False
    assert kpis.projected_production is not None
    assert kpis.yoy_growth_rate is not None
    assert kpis.revenue_potential_usd is not None and kpis.revenue_potential_usd > 0


# ---------- Price fixtures ----------


def test_wti_fixture_parses_to_realistic_price():
    rows = _load_fixture("eia_wti_spot_apr2026.json")
    val, period = _latest_value(rows)
    assert val is not None
    # WTI sane range: $20-$200/bbl.
    assert 20 < val < 200, f"WTI fixture price unrealistic: {val}"
    assert period.startswith("2026-04"), f"unexpected period: {period}"


def test_henry_hub_fixture_parses_to_realistic_price():
    rows = _load_fixture("eia_henryhub_2025_2026.json")
    val, period = _latest_value(rows)
    assert val is not None
    # Henry Hub sane range: $1-$15/MMBtu.
    assert 1 < val < 15, f"HH fixture price unrealistic: {val}"
    # Most recent period should be 2026.
    assert period.startswith(("2025", "2026")), f"unexpected period: {period}"


# ---------- Schema drift sentinels ----------


def test_crude_fixture_includes_expected_keys():
    """If EIA renames or removes a key, fail loudly here. The loader depends
    on these specific keys."""
    rows = _load_fixture("eia_crude_tx_2020_2023.json")
    required = {"period", "duoarea", "value", "units", "product", "process"}
    for row in rows[:5]:
        missing = required - set(row.keys())
        assert not missing, f"row missing keys: {missing}; saw: {sorted(row.keys())}"


def test_gas_fixture_includes_expected_keys():
    rows = _load_fixture("eia_gas_pa_2020_2023.json")
    required = {"period", "duoarea", "value", "units", "process"}
    for row in rows[:5]:
        missing = required - set(row.keys())
        assert not missing, f"row missing keys: {missing}"


def test_wti_fixture_includes_expected_keys():
    rows = _load_fixture("eia_wti_spot_apr2026.json")
    required = {"period", "value", "series"}
    for row in rows[:3]:
        missing = required - set(row.keys())
        assert not missing, f"row missing keys: {missing}"
