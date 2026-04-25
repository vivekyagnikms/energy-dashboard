"""Unit tests for the AI tool router.

No LLM calls. Each test fabricates a tiny DataFrame + ForecastEngine and
verifies that execute_tool() validates inputs, executes the right
implementation, and returns a typed dict the LLM can consume.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.ai.tools import (
    execute_tool,
    resolve_product,
    resolve_region_code,
)
from src.data.schema import Product
from src.forecast.engine import ForecastEngine


def _df(values: dict[int, float], *, region: str = "STX", region_name: str = "Texas",
        product: str = Product.CRUDE_OIL, unit: str = "MBBL", n_months: int = 12) -> pd.DataFrame:
    return pd.DataFrame([
        {"region_code": region, "region_name": region_name, "product": product,
         "year": y, "value": v, "unit": unit, "n_months": n_months}
        for y, v in values.items()
    ])


# ---------- region/product resolvers ----------


def test_region_resolver_accepts_full_name_code_and_abbr():
    assert resolve_region_code("Texas") == "STX"
    assert resolve_region_code("STX") == "STX"
    assert resolve_region_code("TX") == "STX"
    assert resolve_region_code("texas") == "STX"  # case-insensitive
    assert resolve_region_code("US") == "NUS"
    assert resolve_region_code("United States") == "NUS"
    assert resolve_region_code("PADD 3") == "R30"
    assert resolve_region_code("padd-1") == "R10"
    assert resolve_region_code("Gulf of Mexico") == "R3FM"


def test_region_resolver_returns_none_for_unknown():
    assert resolve_region_code("Atlantis") is None
    assert resolve_region_code("") is None


def test_product_resolver():
    assert resolve_product("crude_oil") == Product.CRUDE_OIL
    assert resolve_product("crude") == Product.CRUDE_OIL
    assert resolve_product("oil") == Product.CRUDE_OIL
    assert resolve_product("natural_gas") == Product.NATURAL_GAS
    assert resolve_product("gas") == Product.NATURAL_GAS
    assert resolve_product("ng") == Product.NATURAL_GAS
    assert resolve_product("methane") is None


# ---------- get_production ----------


def test_get_production_returns_actual_for_known_year():
    df = _df({2020 + i: 1000.0 + i for i in range(6)})
    engine = ForecastEngine(df)
    r = execute_tool("get_production",
                     {"region": "Texas", "product": "crude_oil", "year": 2024},
                     df, engine)
    assert r["ok"] is True
    assert r["data"]["value"] == 1004.0
    assert r["data"]["is_forecast"] is False
    assert r["data"]["unit"] == "MBBL"


def test_get_production_returns_forecast_for_future_year():
    df = _df({2020 + i: 1000.0 + 10.0 * i for i in range(6)})
    engine = ForecastEngine(df)
    r = execute_tool("get_production",
                     {"region": "TX", "product": "oil", "year": 2030},
                     df, engine)
    assert r["ok"] is True
    assert r["data"]["is_forecast"] is True


def test_get_production_unknown_region_errors_cleanly():
    df = _df({2020 + i: 1000.0 + i for i in range(6)})
    engine = ForecastEngine(df)
    r = execute_tool("get_production",
                     {"region": "Atlantis", "product": "crude", "year": 2024},
                     df, engine)
    assert r["ok"] is False
    assert "Unknown region" in r["error"]


def test_get_production_invalid_args_rejected_by_pydantic():
    df = _df({2020 + i: 1000.0 + i for i in range(6)})
    engine = ForecastEngine(df)
    r = execute_tool("get_production",
                     {"region": "TX", "product": "moonshine", "year": 2024},
                     df, engine)
    assert r["ok"] is False
    assert "Invalid arguments" in r["error"]


# ---------- compare_regions ----------


def test_compare_regions_returns_sorted_descending():
    df = pd.concat([
        _df({2024: 100.0}, region="STX", region_name="Texas"),
        _df({2024: 500.0}, region="SND", region_name="North Dakota"),
        _df({2024: 50.0}, region="SNM", region_name="New Mexico"),
    ], ignore_index=True)
    engine = ForecastEngine(df)
    r = execute_tool("compare_regions",
                     {"regions": ["TX", "ND", "NM"], "product": "crude_oil", "year": 2024},
                     df, engine)
    assert r["ok"] is True
    values = [row["value"] for row in r["data"]["rows"]]
    assert values == sorted(values, reverse=True)


def test_compare_regions_skips_invalid_with_note():
    df = _df({2024: 100.0})
    engine = ForecastEngine(df)
    r = execute_tool("compare_regions",
                     {"regions": ["TX", "Atlantis"], "product": "crude_oil", "year": 2024},
                     df, engine)
    assert r["ok"] is True
    assert any("Atlantis" in n for n in r["notes"])


# ---------- get_anomalies ----------


def test_anomalies_flagged_only_above_z_threshold():
    # Stable history with one big spike.
    values = {2010 + i: 100.0 for i in range(10)}
    values[2018] = 300.0  # one extreme value
    df = _df(values)
    engine = ForecastEngine(df)
    r = execute_tool("get_anomalies",
                     {"region": "TX", "product": "crude_oil", "z_threshold": 1.5},
                     df, engine)
    assert r["ok"] is True
    flagged_years = {a["year"] for a in r["data"]["anomalies"]}
    assert 2018 in flagged_years or 2019 in flagged_years  # spike year or post-spike snap-back


# ---------- list_regions ----------


def test_list_regions_marks_data_availability():
    df = _df({2024: 100.0}, region="STX")
    engine = ForecastEngine(df)
    r = execute_tool("list_regions", {}, df, engine)
    assert r["ok"] is True
    by_code = {row["code"]: row for row in r["data"]["regions"]}
    assert by_code["STX"]["has_data"] is True
    assert by_code["SVT"]["has_data"] is False  # Vermont — no data in our fixture


# ---------- unknown tool ----------


def test_unknown_tool_returns_clean_error():
    df = _df({2024: 100.0})
    engine = ForecastEngine(df)
    r = execute_tool("delete_database", {}, df, engine)
    assert r["ok"] is False
    assert "Unknown tool" in r["error"]
