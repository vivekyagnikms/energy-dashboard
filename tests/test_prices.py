"""Tests for the live commodity-price feed.

Live API calls are not exercised here — they are tested manually during
build. These tests verify the fallback contract and the label formatting,
which is what shows up in the UI when the live fetch fails.
"""

from __future__ import annotations

from src.data.prices import (
    ILLUSTRATIVE_PRICES,
    CommodityPrices,
    _latest_value,
)


def test_illustrative_prices_match_kpi_constants():
    from src.kpis.calculators import HENRY_HUB_USD_PER_MMBTU, WTI_PRICE_USD_PER_BBL

    assert ILLUSTRATIVE_PRICES.wti_usd_per_bbl == WTI_PRICE_USD_PER_BBL
    assert ILLUSTRATIVE_PRICES.henry_hub_usd_per_mmbtu == HENRY_HUB_USD_PER_MMBTU
    assert ILLUSTRATIVE_PRICES.is_live is False


def test_label_marks_illustrative_when_not_live():
    p = CommodityPrices(75.0, 3.0, "", False)
    assert "illustrative" in p.wti_label
    assert "illustrative" in p.henry_hub_label


def test_label_carries_as_of_date_when_live():
    p = CommodityPrices(91.06, 3.04, "2026-04-15", True)
    assert "2026-04-15" in p.wti_label
    assert "2026-04-15" in p.henry_hub_label
    assert "illustrative" not in p.wti_label


def test_latest_value_picks_most_recent_period():
    rows = [
        {"period": "2026-01-01", "value": "50"},
        {"period": "2026-04-15", "value": "91.06"},
        {"period": "2026-03-01", "value": "85"},
    ]
    val, period = _latest_value(rows)
    assert val == 91.06
    assert period == "2026-04-15"


def test_latest_value_skips_missing_values():
    rows = [
        {"period": "2026-04-15", "value": ""},
        {"period": "2026-03-01", "value": None},
        {"period": "2026-02-01", "value": "85"},
    ]
    val, period = _latest_value(rows)
    assert val == 85
    assert period == "2026-02-01"


def test_latest_value_returns_none_for_empty():
    val, period = _latest_value([])
    assert val is None
    assert period == ""
