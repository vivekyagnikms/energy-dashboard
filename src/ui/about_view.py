"""About & methodology tab.

Three sections:
- Live data provenance (source URL, fetch timestamp, coverage stats)
- Forecast accuracy backtest (per-region MAPE, plus a drill-down chart)
- Methodology blurb pointing to docs/.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.data.prices import CommodityPrices
from src.data.schema import Product
from src.forecast.backtest import backtest_all_regions, backtest_region
from src.forecast.engine import ForecastEngine
from src.utils.cache import CACHE_DIR


def _last_fetch_iso() -> str:
    candidates = list(CACHE_DIR.glob("*.parquet"))
    if not candidates:
        return "unknown"
    mtime = max(c.stat().st_mtime for c in candidates)
    return datetime.utcfromtimestamp(mtime).isoformat(timespec="seconds") + "Z"


def render_about_tab(
    df: pd.DataFrame,
    engine: ForecastEngine,
    prices: CommodityPrices,
) -> None:
    st.header("🔬 About & methodology")
    st.caption(
        "How the dashboard works, what data feeds it, and how well the "
        "forecast model performs on years we already know."
    )

    # ---- Provenance ----
    st.subheader("📚 Data provenance")
    col1, col2 = st.columns(2)
    with col1:
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
            f"""
**Source:** [U.S. Energy Information Administration — API v2](https://www.eia.gov/opendata/)

**Production series:**
- Crude oil: `petroleum/crd/crpdn` · process FPF · unit MBBL
- Natural gas: `natural-gas/prod/sum` · process VGM · unit MMCF

**Coverage:** {n_rows:,} annual rows · {n_regions} regions · years {year_min}–{year_max}

**Last full year of data:** {last_full}
            """
        )
    with col2:
        live_label = "✅ Live" if prices.is_live else "⚠️ Default constants"
        st.markdown(
            f"""
**Cache last refreshed:** `{_last_fetch_iso()}`

**Live commodity prices:** {live_label}
- {prices.wti_label}
- {prices.henry_hub_label}

**Region coverage:**
- 1 national total
- 1 federal offshore (Gulf of Mexico)
- 5 PADDs
- 50 states + DC (non-producers show empty state)
            """
        )

    st.divider()

    # ---- Backtest ----
    st.subheader("📈 Forecast accuracy (walk-forward backtest)")
    st.caption(
        "For each region, we re-run the linear-regression forecast as if every "
        "historical year were unknown — train on data up to year Y−1, predict "
        "Y, compare to actual. MAPE is the mean absolute percent error across "
        "all such holdout years."
    )

    bt_product = st.radio(
        "Product",
        options=("Crude Oil", "Natural Gas"),
        horizontal=True,
        key="bt_product",
    )
    product_code = (
        Product.CRUDE_OIL if bt_product == "Crude Oil" else Product.NATURAL_GAS
    )

    with st.spinner("Running walk-forward backtest…"):
        results_df = backtest_all_regions(df, product_code, min_holdout_years=3)

    if results_df.empty:
        st.info("No regions have enough history for a meaningful backtest.")
        return

    summary_col, drill_col = st.columns([1, 1])

    # ---- Summary table ----
    with summary_col:
        st.markdown("**Per-region accuracy (best-calibrated first)**")
        display_df = results_df.copy()
        display_df["region"] = display_df["region_name"]
        display_df = display_df[
            ["region", "n_holdout_years", "mape_pct", "bias_pct", "r_squared_avg"]
        ]
        st.dataframe(
            display_df,
            column_config={
                "region": "Region",
                "n_holdout_years": st.column_config.NumberColumn(
                    "Holdout yrs", format="%d"
                ),
                "mape_pct": st.column_config.NumberColumn(
                    "MAPE",
                    format="%.1f%%",
                    help="Mean absolute percent error across holdout years. Lower = better.",
                ),
                "bias_pct": st.column_config.NumberColumn(
                    "Bias",
                    format="%+.1f%%",
                    help="Mean signed error. Positive = forecast tends high.",
                ),
                "r_squared_avg": st.column_config.NumberColumn(
                    "Avg R²",
                    format="%.2f",
                ),
            },
            hide_index=True,
            use_container_width=True,
            height=400,
        )
        st.caption(
            f"Median MAPE across {len(results_df)} regions: "
            f"**{results_df['mape_pct'].median():.1f}%**. "
            f"Best: **{results_df.iloc[0]['region_name']}** "
            f"({results_df.iloc[0]['mape_pct']:.1f}% MAPE)."
        )

    # ---- Drill-down chart for one region ----
    with drill_col:
        st.markdown("**Drill into one region**")
        region_options = list(results_df["region_name"])
        chosen_name = st.selectbox(
            "Region",
            options=region_options,
            index=0,
            key="bt_region",
        )
        chosen_code = results_df.loc[
            results_df["region_name"] == chosen_name, "region_code"
        ].iloc[0]

        result = backtest_region(df, str(chosen_code), product_code)
        if result is None:
            st.info("Insufficient data for this region.")
            return

        rows = result.rows
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=rows["year"],
                y=rows["actual"],
                mode="lines+markers",
                name="Actual",
                line=dict(color="#F59E0B", width=3),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=rows["year"],
                y=rows["predicted"],
                mode="lines+markers",
                name="Walk-forward forecast",
                line=dict(color="#60A5FA", width=3, dash="dash"),
            )
        )
        unit_label = "MBBL" if product_code == Product.CRUDE_OIL else "MMCF"
        fig.update_layout(
            title=f"{chosen_name} — actual vs walk-forward forecast",
            xaxis_title="Year",
            yaxis_title=unit_label,
            height=300,
            margin=dict(l=10, r=10, t=40, b=20),
            hovermode="x unified",
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(255,255,255,0.02)",
            legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            f"MAPE: **{result.mape_pct:.1f}%** · Bias: "
            f"**{result.bias_pct:+.1f}%** · "
            f"holdout years: {result.n_holdout_years}"
        )

    st.divider()

    # ---- Methodology pointers ----
    st.subheader("🧭 Methodology")
    st.markdown(
        """
- **Forecast model:** linear regression on annual full-year totals, ±1.96σ confidence band.
  Partial current year excluded from training. See [`src/forecast/engine.py`](https://github.com/Community-Dreams-Foundation-Hackathons/energy-intelligence-system-vivekyagnikms/blob/main/src/forecast/engine.py).
- **AI grounding:** Gemini 2.5 Flash with mandatory tool calls; every numeric token in the
  final answer is cross-checked against tool returns within ±1%. 13 guardrail layers documented in [`docs/architecture.md`](https://github.com/Community-Dreams-Foundation-Hackathons/energy-intelligence-system-vivekyagnikms/blob/main/docs/architecture.md).
- **KPI definitions:** [`docs/kpi_definitions.md`](https://github.com/Community-Dreams-Foundation-Hackathons/energy-intelligence-system-vivekyagnikms/blob/main/docs/kpi_definitions.md).
- **Resilience:** parquet cache (24h) → live API → bundled seed snapshot (1,231 rows committed in `data/seed/`). The demo never hard-fails.
        """
    )
