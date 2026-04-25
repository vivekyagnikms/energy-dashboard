"""Compare regions tab. Pick 2-5 regions and see them overlaid on one chart,
plus a side-by-side KPI table."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.data.prices import CommodityPrices
from src.data.regions import ALL_REGIONS, RegionGroup
from src.data.schema import Product
from src.forecast.engine import ForecastEngine
from src.kpis.calculators import compute_kpi_set

# Distinct, color-blind friendly palette for up to 5 overlaid regions.
_PALETTE: tuple[str, ...] = (
    "#F59E0B",  # amber
    "#60A5FA",  # blue
    "#34D399",  # green
    "#F472B6",  # pink
    "#A78BFA",  # purple
)


def _supported_regions(df: pd.DataFrame, engine: ForecastEngine, product: str) -> list:
    """Regions with at least 5 full years of data for this product."""
    return [r for r in ALL_REGIONS if engine.is_supported(r.code, product)]


def _default_top5(df: pd.DataFrame, engine: ForecastEngine, product: str) -> list[str]:
    """Pick the 5 most recent top producers as sensible defaults."""
    last_full = (
        int(df.loc[df["n_months"] >= 12, "year"].max())
        if (df["n_months"] >= 12).any()
        else int(df["year"].max())
    )
    sub = df[(df["product"] == product) & (df["year"] == last_full)].sort_values(
        "value", ascending=False
    )
    # Drop national + PADDs + offshore from the default suggestion so the
    # comparison is between states. User can re-add them.
    state_codes = {r.code for r in ALL_REGIONS if r.group is RegionGroup.STATE}
    state_rows = sub[sub["region_code"].isin(state_codes)]
    return list(state_rows["region_name"].head(5))


def render_compare_tab(
    df: pd.DataFrame,
    engine: ForecastEngine,
    prices: CommodityPrices,
) -> None:
    st.header("🆚 Compare regions")
    st.caption(
        "Overlay the production history + forecast for 2 to 5 regions on one "
        "chart, with a side-by-side KPI table for the selected year."
    )

    # ---- Controls ----
    c1, c2 = st.columns([1, 1])
    with c1:
        product_label = st.radio(
            "Product",
            options=("Crude Oil", "Natural Gas"),
            horizontal=True,
            key="compare_product",
        )
        product = (
            Product.CRUDE_OIL if product_label == "Crude Oil" else Product.NATURAL_GAS
        )
    with c2:
        last_full = (
            int(df.loc[df["n_months"] >= 12, "year"].max())
            if (df["n_months"] >= 12).any()
            else int(df["year"].max())
        )
        year = st.slider(
            "Year (for the KPI table)",
            min_value=int(df["year"].min()),
            max_value=last_full + 5,
            value=last_full,
            step=1,
            key="compare_year",
        )

    supported = _supported_regions(df, engine, product)
    if not supported:
        st.info("No regions have enough data to compare for this product.")
        return

    region_names = [r.name for r in supported]
    defaults = _default_top5(df, engine, product)
    defaults = [d for d in defaults if d in region_names][:5]

    selected_names = st.multiselect(
        "Regions to compare (2–5)",
        options=region_names,
        default=defaults if len(defaults) >= 2 else region_names[:5],
        key="compare_regions",
        help="Includes national, PADDs, and producing states.",
    )

    if len(selected_names) < 2:
        st.info("Pick at least 2 regions to compare.")
        return
    if len(selected_names) > 5:
        st.warning("Showing the first 5 selected regions for chart legibility.")
        selected_names = selected_names[:5]

    selected_regions = [r for r in supported if r.name in selected_names]

    # ---- Overlaid chart ----
    unit = "MBBL" if product == Product.CRUDE_OIL else "MMCF"
    fig = go.Figure()
    for i, region in enumerate(selected_regions):
        color = _PALETTE[i % len(_PALETTE)]
        history = engine.history(region.code, product)
        if not history.empty:
            fig.add_trace(
                go.Scatter(
                    x=history["year"],
                    y=history["value"],
                    mode="lines+markers",
                    name=f"{region.name} (history)",
                    line=dict(color=color, width=2.5),
                    marker=dict(size=5),
                    legendgroup=region.name,
                )
            )

        # Forecast extension for the same region.
        last_full_year = int(history["year"].max()) if not history.empty else last_full
        fc = engine.forecast_range(region.code, product, end_year=last_full_year + 5)
        if not fc.empty and not history.empty:
            # Connect last history point to forecast for visual continuity.
            bridge_year = int(history["year"].iloc[-1])
            bridge_value = float(history["value"].iloc[-1])
            fc_x = [bridge_year] + list(fc["year"])
            fc_y = [bridge_value] + list(fc["value"])
            fig.add_trace(
                go.Scatter(
                    x=fc_x,
                    y=fc_y,
                    mode="lines",
                    name=f"{region.name} (forecast)",
                    line=dict(color=color, width=2.5, dash="dash"),
                    legendgroup=region.name,
                    showlegend=False,
                )
            )

    fig.update_layout(
        title=f"{product_label} production · {len(selected_regions)} regions",
        xaxis_title="Year",
        yaxis_title=f"{product_label} ({unit})",
        height=480,
        margin=dict(l=10, r=10, t=60, b=40),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.02)",
    )
    st.plotly_chart(fig, use_container_width=True)

    # ---- Side-by-side KPI table ----
    st.subheader(f"📊 KPI snapshot · {year}")
    rows: list[dict] = []
    for region in selected_regions:
        if product == Product.CRUDE_OIL:
            wti, hh = prices.wti_usd_per_bbl, prices.henry_hub_usd_per_mmbtu
            price_label = prices.wti_label
        else:
            wti, hh = prices.wti_usd_per_bbl, prices.henry_hub_usd_per_mmbtu
            price_label = prices.henry_hub_label
        kpis = compute_kpi_set(
            df,
            engine,
            region.code,
            product,
            year,
            wti_price=wti,
            henry_hub_price=hh,
            revenue_price_label=price_label,
        )
        rows.append(
            {
                "Region": region.name,
                "Type": "🔮 Forecast" if kpis.is_forecast else "📊 Actual",
                "Production": kpis.projected_production,
                "YoY %": kpis.yoy_growth_rate * 100 if kpis.yoy_growth_rate else None,
                "5y CAGR %": kpis.five_year_cagr * 100 if kpis.five_year_cagr else None,
                "Volatility": kpis.volatility,
                "Revenue (USD B)": (
                    kpis.revenue_potential_usd / 1e9
                    if kpis.revenue_potential_usd
                    else None
                ),
            }
        )
    kpi_df = pd.DataFrame(rows).sort_values("Production", ascending=False)
    st.dataframe(
        kpi_df,
        column_config={
            "Region": "Region",
            "Type": "Type",
            "Production": st.column_config.NumberColumn(
                f"Production ({unit})", format="%,.0f"
            ),
            "YoY %": st.column_config.NumberColumn("YoY", format="%+.1f%%"),
            "5y CAGR %": st.column_config.NumberColumn("5-yr CAGR", format="%+.1f%%"),
            "Volatility": st.column_config.NumberColumn("Volatility", format="%.2f"),
            "Revenue (USD B)": st.column_config.NumberColumn(
                "Revenue (USD B)",
                format="%.2f",
            ),
        },
        hide_index=True,
        use_container_width=True,
    )
    if any(r["Revenue (USD B)"] is not None for r in rows):
        st.caption(f"Revenue computed at {price_label}.")
