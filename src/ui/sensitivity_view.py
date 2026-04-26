"""2D sensitivity heatmap: volume × price → projected revenue.

The problem statement specifically asks for a 'matrix or heat map showing
how Projected Production Estimate changes across two input variables...
color-coded cells (red = weak, green = strong), tied to the year selector.'

We render that as a Plotly heatmap on the Overview tab below the existing
1D slider, so analysts get both the precise single-axis tweak and the
broader 2D scenario view.
"""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from src.data.prices import CommodityPrices
from src.data.schema import Product
from src.forecast.engine import ForecastEngine
from src.kpis.calculators import MMBTU_PER_MMCF, get_actual_or_forecast
from src.utils.cache import CACHE_DIR  # noqa: F401  (kept so import order stays consistent)

# 7×7 grid: ±30% on volume, ±30% on price, in 10-point steps.
_VOLUME_AXIS_PCT: tuple[int, ...] = (-30, -20, -10, 0, 10, 20, 30)
_PRICE_AXIS_PCT: tuple[int, ...] = (-30, -20, -10, 0, 10, 20, 30)


def render_sensitivity_heatmap(
    df,  # pd.DataFrame
    engine: ForecastEngine,
    region_code: str,
    region_name: str,
    product: str,
    selected_year: int,
    prices: CommodityPrices,
) -> None:
    """2D scenario heatmap. Each cell is projected revenue (USD billions)
    at that combination of volume adjustment × price adjustment."""
    base_volume, _ = get_actual_or_forecast(
        df, engine, region_code, product, selected_year
    )
    if base_volume is None:
        st.caption(
            "Scenario heatmap unavailable: no production estimate for this year."
        )
        return

    # Pick the price axis label/value matching the product.
    if product == Product.CRUDE_OIL:
        base_price = prices.wti_usd_per_bbl
        price_unit_label = "WTI USD/bbl"
        # Revenue for crude: volume_MBBL * 1000 * USD/bbl
        revenue_factor = 1000.0
    else:
        base_price = prices.henry_hub_usd_per_mmbtu
        price_unit_label = "Henry Hub USD/MMBtu"
        # Revenue for gas: volume_MMCF * MMBtu/MMCF * USD/MMBtu
        revenue_factor = MMBTU_PER_MMCF

    # Build the matrix: rows = price adjustments (top→bottom: +30% to -30%),
    # cols = volume adjustments (left→right: -30% to +30%).
    price_adjustments = np.array(_PRICE_AXIS_PCT)[::-1]  # reverse for plot orientation
    volume_adjustments = np.array(_VOLUME_AXIS_PCT)

    revenue_matrix = np.zeros((len(price_adjustments), len(volume_adjustments)))
    for i, p_pct in enumerate(price_adjustments):
        for j, v_pct in enumerate(volume_adjustments):
            adjusted_volume = base_volume * (1.0 + v_pct / 100.0)
            adjusted_price = base_price * (1.0 + p_pct / 100.0)
            revenue_matrix[i, j] = adjusted_volume * revenue_factor * adjusted_price

    # Convert to USD billions for display.
    rev_b = revenue_matrix / 1e9
    base_rev_b = (base_volume * revenue_factor * base_price) / 1e9

    # Axis labels.
    x_labels = [f"{p:+d}%" for p in volume_adjustments]
    y_labels = [f"{p:+d}%" for p in price_adjustments]

    # Hover text: full breakdown per cell.
    hover_text = []
    for i, p_pct in enumerate(price_adjustments):
        row = []
        for j, v_pct in enumerate(volume_adjustments):
            adjusted_volume = base_volume * (1.0 + v_pct / 100.0)
            adjusted_price = base_price * (1.0 + p_pct / 100.0)
            unit = "MBBL" if product == Product.CRUDE_OIL else "MMCF"
            row.append(
                f"<b>Volume: {v_pct:+d}%</b> ({adjusted_volume:,.0f} {unit})<br>"
                f"<b>Price: {p_pct:+d}%</b> ({adjusted_price:.2f} {price_unit_label.split()[1]})<br>"
                f"Revenue: USD {rev_b[i, j]:.2f}B"
            )
        hover_text.append(row)

    fig = go.Figure(
        data=go.Heatmap(
            z=rev_b,
            x=x_labels,
            y=y_labels,
            text=[[f"${v:.1f}B" for v in row] for row in rev_b],
            texttemplate="%{text}",
            textfont={"size": 11},
            hovertext=hover_text,
            hovertemplate="%{hovertext}<extra></extra>",
            colorscale="RdYlGn",  # red (weak) → yellow → green (strong)
            colorbar=dict(
                title="USD<br>billions",
                tickformat=".1f",
            ),
        )
    )

    # Mark the base case (0% × 0%) explicitly.
    base_x_idx = list(volume_adjustments).index(0)
    base_y_idx = list(price_adjustments).index(0)
    fig.add_shape(
        type="rect",
        x0=base_x_idx - 0.5,
        x1=base_x_idx + 0.5,
        y0=base_y_idx - 0.5,
        y1=base_y_idx + 0.5,
        line=dict(color="#FAFAFA", width=2),
        fillcolor="rgba(0,0,0,0)",
    )

    pretty = "Crude Oil" if product == Product.CRUDE_OIL else "Natural Gas"
    fig.update_layout(
        title=(
            f"{region_name} · {pretty} · {selected_year} · "
            f"Revenue sensitivity (base: USD {base_rev_b:.2f}B)"
        ),
        xaxis_title="Volume adjustment (production ±%)",
        yaxis_title=f"Price adjustment ({price_unit_label} ±%)",
        height=420,
        margin=dict(l=10, r=10, t=60, b=40),
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        f"Color scale: **red = weak revenue, green = strong**. White outline marks "
        f"the base case (0% × 0% = USD {base_rev_b:.2f}B). "
        f"Base price: **{base_price:.2f} {price_unit_label}** "
        f"({'live' if prices.is_live else 'illustrative'})."
    )
