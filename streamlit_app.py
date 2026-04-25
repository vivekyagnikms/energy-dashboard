"""Streamlit entry point for the U.S. Oil & Gas Production Intelligence dashboard.

Run locally:
    streamlit run streamlit_app.py

Deploys to Streamlit Community Cloud unchanged; secrets come from
.streamlit/secrets.toml locally and the Streamlit Cloud dashboard in prod.
"""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd
import streamlit as st

from src.ai.client import GeminiClient
from src.data.loader import load_production_data
from src.data.schema import Product
from src.forecast.engine import ForecastEngine
from src.kpis.calculators import compute_kpi_set
from src.ui.charts import render_history_forecast_chart
from src.ui.chat_panel import render_ai_panel
from src.ui.empty_state import render_empty_state
from src.ui.kpi_cards import render_kpi_cards
from src.ui.sidebar import render_sidebar

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")

# --- Page setup ---
st.set_page_config(
    page_title="U.S. Oil & Gas Production Intelligence",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)


# --- Data loading (cached across reruns; user can force refresh from sidebar) ---
@st.cache_data(ttl=24 * 60 * 60, show_spinner="Fetching EIA production data…")
def _load_data() -> pd.DataFrame:
    """Cached wrapper around load_production_data. Streamlit's cache memoizes
    across the session; the underlying parquet cache survives across sessions.
    """
    api_key = st.secrets["EIA_API_KEY"]
    return load_production_data(api_key)


def _resolve_unit(df: pd.DataFrame, product: str) -> str:
    """Lookup the unit for a product from the DataFrame; '' if unknown."""
    if df.empty:
        return ""
    match = df.loc[df["product"] == product, "unit"]
    return str(match.iloc[0]) if not match.empty else ""


@st.cache_resource
def _ai_client() -> GeminiClient:
    """One Gemini client per app process. Cached as a resource (not data) so
    the underlying SDK Client and its connection pool are reused.
    """
    api_key = st.secrets.get("GEMINI_API_KEY")
    mock_flag = bool(st.secrets.get("MOCK_AI", False))
    if mock_flag or not api_key:
        return GeminiClient(api_key=None, mock=True)
    return GeminiClient(api_key=api_key, mock=False)


def main() -> None:
    df = _load_data()
    engine = ForecastEngine(df)

    selection = render_sidebar(df)

    # --- Header ---
    st.title("⚡ U.S. Oil & Gas Production Intelligence")
    st.caption(
        "Live EIA data · linear-regression forecasting · grounded AI analysis. "
        "Built for business-development analysts evaluating regional opportunities."
    )

    is_supported = engine.is_supported(selection.region.code, selection.product)

    # --- Empty state for non-producing regions (KPIs and chart skipped) ---
    if not is_supported:
        render_empty_state(selection.region, selection.product)
        # Still render AI panel; it shows a friendly notice for unsupported regions.
        st.divider()
        render_ai_panel(
            client=_ai_client(),
            df=df, engine=engine,
            region_code=selection.region.code,
            region_name=selection.region.name,
            product=selection.product,
            selected_year=selection.year,
            is_supported=False,
        )
        return

    # --- KPIs ---
    kpis = compute_kpi_set(
        df, engine,
        selection.region.code, selection.product, selection.year,
    )
    render_kpi_cards(kpis)

    st.divider()

    # --- Chart ---
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

    st.divider()

    # --- AI panel ---
    render_ai_panel(
        client=_ai_client(),
        df=df, engine=engine,
        region_code=selection.region.code,
        region_name=selection.region.name,
        product=selection.product,
        selected_year=selection.year,
        is_supported=True,
    )

    # --- Footer / provenance (basic; richer panel in Phase 6) ---
    st.divider()
    last_data_year = int(df["year"].max())
    last_full = int(df.loc[df["n_months"] >= 12, "year"].max())
    st.caption(
        f"Source: EIA API v2 · last data point {last_data_year} "
        f"(last full year: {last_full}) · cached locally for 24h. "
        f"Built {date.today().isoformat()}."
    )


if __name__ == "__main__":
    main()
