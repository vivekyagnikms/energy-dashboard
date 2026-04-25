"""Streamlit entry point for the U.S. Oil & Gas Production Intelligence dashboard.

Run locally:
    streamlit run streamlit_app.py

Tab layout:
    📊 Overview        — single-region KPIs, chart, AI panel, tools
    🆚 Compare         — multi-region overlaid history + forecast + KPI ranking
    🗺️ Map             — US choropleth by production
    🎯 Recommendations — AI-ranked top opportunities
    🔬 About            — provenance, methodology, forecast accuracy backtest

Sidebar selection drives the Overview tab. Other tabs have their own selectors
so the user can compare or browse without losing the single-region context.
"""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd
import streamlit as st

from src.ai.client import GeminiClient
from src.data.loader import load_production_data
from src.data.prices import CommodityPrices, fetch_live_prices
from src.forecast.engine import ForecastEngine
from src.kpis.calculators import compute_kpi_set
from src.ui.charts import render_history_forecast_chart
from src.ui.chat_panel import render_ai_panel
from src.ui.compare_view import render_compare_tab
from src.ui.empty_state import render_empty_state
from src.ui.header import render_header
from src.ui.kpi_cards import render_kpi_cards
from src.ui.map_view import render_map_tab
from src.ui.recommendations_view import render_recommendations_tab
from src.ui.about_view import render_about_tab
from src.ui.sidebar import render_sidebar
from src.ui.tools_panel import render_tools_panel

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")

# --- Page setup ---
st.set_page_config(
    page_title="U.S. Oil & Gas Production Intelligence",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)


# --- Cached resources ---


@st.cache_data(ttl=24 * 60 * 60, show_spinner="Fetching EIA production data…")
def _load_data() -> pd.DataFrame:
    """Cached production data. ttl=24h matches the parquet cache TTL."""
    api_key = st.secrets["EIA_API_KEY"]
    return load_production_data(api_key)


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def _load_prices() -> CommodityPrices:
    """Live WTI + Henry Hub spot prices, refreshed every 6h.

    Falls back to illustrative constants if the EIA price endpoints fail —
    the calling code can read `is_live` to disclose this in the UI.
    """
    api_key = st.secrets["EIA_API_KEY"]
    return fetch_live_prices(api_key)


@st.cache_resource
def _ai_client() -> GeminiClient:
    """One Gemini client per app process."""
    api_key = st.secrets.get("GEMINI_API_KEY")
    mock_flag = bool(st.secrets.get("MOCK_AI", False))
    if mock_flag or not api_key:
        return GeminiClient(api_key=None, mock=True)
    return GeminiClient(api_key=api_key, mock=False)


# --- Helpers ---


def _resolve_unit(df: pd.DataFrame, product: str) -> str:
    if df.empty:
        return ""
    match = df.loc[df["product"] == product, "unit"]
    return str(match.iloc[0]) if not match.empty else ""


# --- Per-tab renderers (Overview is inline; the rest are in src/ui/) ---


def _render_overview_tab(
    df: pd.DataFrame,
    engine: ForecastEngine,
    prices: CommodityPrices,
    selection,
) -> None:
    """Single-region dashboard: KPIs + chart + tools row + AI panel."""
    is_supported = engine.is_supported(selection.region.code, selection.product)

    if not is_supported:
        render_empty_state(selection.region, selection.product)
        st.divider()
        render_ai_panel(
            client=_ai_client(),
            df=df,
            engine=engine,
            region_code=selection.region.code,
            region_name=selection.region.name,
            product=selection.product,
            selected_year=selection.year,
            is_supported=False,
        )
        return

    # Build the price label that the KPI card surfaces.
    if selection.product == "crude_oil":
        price_label = prices.wti_label
        wti = prices.wti_usd_per_bbl
        hh = prices.henry_hub_usd_per_mmbtu
    else:
        price_label = prices.henry_hub_label
        wti = prices.wti_usd_per_bbl
        hh = prices.henry_hub_usd_per_mmbtu

    kpis = compute_kpi_set(
        df,
        engine,
        selection.region.code,
        selection.product,
        selection.year,
        wti_price=wti,
        henry_hub_price=hh,
        revenue_price_label=price_label,
    )
    render_kpi_cards(kpis)

    st.divider()

    unit = _resolve_unit(df, selection.product)
    last_full_year = int(df.loc[df["n_months"] >= 12, "year"].max())
    chart_end = max(selection.year + 2, last_full_year + 5)
    render_history_forecast_chart(
        engine,
        region_code=selection.region.code,
        region_name=selection.region.name,
        product=selection.product,
        selected_year=selection.year,
        end_year=chart_end,
        unit=unit,
    )

    render_tools_panel(
        df=df,
        engine=engine,
        region_code=selection.region.code,
        region_name=selection.region.name,
        product=selection.product,
        selected_year=selection.year,
        forecast_end_year=chart_end,
    )

    st.divider()

    render_ai_panel(
        client=_ai_client(),
        df=df,
        engine=engine,
        region_code=selection.region.code,
        region_name=selection.region.name,
        product=selection.product,
        selected_year=selection.year,
        is_supported=True,
    )


def main() -> None:
    df = _load_data()
    prices = _load_prices()
    engine = ForecastEngine(df)
    selection = render_sidebar(df)

    # --- Title + at-a-glance header ---
    st.title("⚡ U.S. Oil & Gas Production Intelligence")
    st.caption(
        "Live EIA data · linear-regression forecasting · Gemini-grounded AI analysis. "
        "Built for business-development analysts evaluating regional opportunities."
    )
    render_header(df, prices)
    st.divider()

    # --- Tabs ---
    overview_tab, compare_tab, map_tab, recs_tab, about_tab = st.tabs(
        [
            "📊 Overview",
            "🆚 Compare regions",
            "🗺️ Map",
            "🎯 Recommendations",
            "🔬 About & methodology",
        ]
    )

    with overview_tab:
        _render_overview_tab(df, engine, prices, selection)

    with compare_tab:
        render_compare_tab(df, engine, prices)

    with map_tab:
        render_map_tab(df, engine, prices, selection)

    with recs_tab:
        render_recommendations_tab(
            df,
            engine,
            prices,
            _ai_client(),
            selected_product=selection.product,
            selected_year=selection.year,
        )

    with about_tab:
        render_about_tab(df, engine, prices)

    # --- Footer ---
    st.divider()
    last_data_year = int(df["year"].max())
    last_full = int(df.loc[df["n_months"] >= 12, "year"].max())
    st.caption(
        f"Source: EIA API v2 · last data point {last_data_year} "
        f"(last full year: {last_full}) · cache TTL 24h. "
        f"Built {date.today().isoformat()}."
    )


if __name__ == "__main__":
    main()
