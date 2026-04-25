"""Tools row beneath the chart: Excel export, provenance, sensitivity slider.

Three Tier-2 polish items kept compact in one row so the chart and AI
panel stay above the fold."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from src.data.schema import Product
from src.forecast.engine import ForecastEngine
from src.kpis.calculators import (
    HENRY_HUB_USD_PER_MMBTU,
    MMBTU_PER_MMCF,
    WTI_PRICE_USD_PER_BBL,
    get_actual_or_forecast,
)
from src.utils.cache import CACHE_DIR
from src.utils.excel_export import build_workbook


def _last_fetch_iso() -> str:
    """ISO timestamp of the live cache file, if present; else 'unknown'."""
    candidates = list(CACHE_DIR.glob("*.parquet"))
    if not candidates:
        return "unknown"
    mtime = max(c.stat().st_mtime for c in candidates)
    return datetime.utcfromtimestamp(mtime).isoformat(timespec="seconds") + "Z"


def render_tools_panel(
    df: pd.DataFrame,
    engine: ForecastEngine,
    region_code: str,
    region_name: str,
    product: str,
    selected_year: int,
    forecast_end_year: int,
) -> None:
    """One row with: Excel export button, provenance expander, sensitivity slider."""
    pretty_product = "crude_oil" if product == Product.CRUDE_OIL else "natural_gas"
    fname = f"{region_name.replace(' ', '_')}_{pretty_product}_{selected_year}.xlsx"

    c1, c2, c3 = st.columns([1, 1, 2])

    # ---- Excel export ----
    with c1:
        try:
            xlsx_bytes = build_workbook(
                engine,
                region_code,
                region_name,
                product,
                selected_year,
                forecast_end_year,
            )
            st.download_button(
                label="📥 Excel export",
                data=xlsx_bytes,
                file_name=fname,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                help="Download a workbook with Historical, Forecast, and KPIs (formulas).",
                use_container_width=True,
            )
        except Exception as e:
            st.button("📥 Excel export", disabled=True, use_container_width=True)
            st.caption(f"export failed: {e}")

    # ---- Provenance ----
    with c2:
        with st.popover("📚 Data provenance", use_container_width=True):
            n_rows = len(df)
            n_regions = df["region_code"].nunique() if not df.empty else 0
            year_min = int(df["year"].min()) if not df.empty else 0
            year_max = int(df["year"].max()) if not df.empty else 0
            last_full = (
                int(df.loc[df["n_months"] >= 12, "year"].max())
                if not df.empty and (df["n_months"] >= 12).any()
                else year_max
            )
            st.markdown(
                "**Source:** [U.S. Energy Information Administration — API v2]"
                "(https://www.eia.gov/opendata/)"
            )
            st.markdown("**Series:**")
            st.markdown("- Crude oil: `petroleum/crd/crpdn` · process FPF · unit MBBL")
            st.markdown(
                "- Natural gas: `natural-gas/prod/sum` · process VGM · unit MMCF"
            )
            st.markdown(f"**Cache last refreshed:** `{_last_fetch_iso()}`")
            st.markdown(
                f"**Coverage:** {n_rows:,} annual rows across "
                f"{n_regions} regions, years {year_min}-{year_max}."
            )
            st.markdown(
                f"**Last full year:** {last_full} (later years are partial or forecast)."
            )
            st.markdown(
                "Forecasts are produced by `src/forecast/engine.py` (linear regression "
                "with ±1.96σ confidence band). Anomalies are flagged statistically "
                "(z-score on YoY %); the LLM only narrates them."
            )

    # ---- Sensitivity ----
    with c3:
        base, is_forecast = get_actual_or_forecast(
            df, engine, region_code, product, selected_year
        )
        if base is None:
            st.caption("Sensitivity unavailable: no production estimate for this year.")
            return
        adj_pct = st.slider(
            "Sensitivity (forecast assumption ±%)",
            min_value=-30,
            max_value=30,
            value=0,
            step=5,
            help="Apply a manual adjustment to the projected production value to "
            "stress-test downstream KPIs. Shown only for the selected year.",
            key="sensitivity_slider",
        )
        adj_factor = 1.0 + (adj_pct / 100.0)
        adj_value = base * adj_factor
        # Revenue at adjusted volume.
        if product == Product.CRUDE_OIL:
            rev = adj_value * 1000.0 * WTI_PRICE_USD_PER_BBL
        else:
            rev = adj_value * MMBTU_PER_MMCF * HENRY_HUB_USD_PER_MMBTU
        unit = "MBBL" if product == Product.CRUDE_OIL else "MMCF"
        delta_value = adj_value - base
        delta_rev = rev - (
            base * 1000.0 * WTI_PRICE_USD_PER_BBL
            if product == Product.CRUDE_OIL
            else base * MMBTU_PER_MMCF * HENRY_HUB_USD_PER_MMBTU
        )
        sub1, sub2 = st.columns(2)
        with sub1:
            st.metric(
                f"Adjusted volume ({selected_year})",
                f"{adj_value:,.0f} {unit}",
                delta=f"{delta_value:+,.0f}" if adj_pct != 0 else None,
            )
        with sub2:
            st.metric(
                "Adjusted revenue (USD)",
                f"USD {rev / 1e9:.2f}B",
                delta=f"{delta_rev / 1e9:+.2f}B" if adj_pct != 0 else None,
            )
