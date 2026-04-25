"""History + forecast chart. Solid past, dashed future, confidence band."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.data.schema import Product
from src.forecast.engine import ForecastEngine

_HISTORY_COLOR = "#F59E0B"  # amber, matches theme primaryColor
_FORECAST_COLOR = "#60A5FA"  # blue, distinct from history
_BAND_COLOR = "rgba(96, 165, 250, 0.18)"

# Industry events worth annotating on multi-year production charts. Each
# event is a (year, label) tuple; we draw a faint vertical line + label
# only when the event year falls inside the chart's x-range.
_EVENT_ANNOTATIONS: tuple[tuple[int, str], ...] = (
    (2014, "OPEC oversupply →\noil price collapse"),
    (2020, "COVID demand shock"),
    (2022, "OPEC+ cuts /\nreshoring demand"),
)


def _y_axis_label(product: str, unit: str) -> str:
    pretty = "Crude Oil" if product == Product.CRUDE_OIL else "Natural Gas"
    if unit.upper() == "MBBL":
        return f"{pretty} (thousand barrels)"
    if unit.upper() == "MMCF":
        return f"{pretty} (million cubic feet)"
    return f"{pretty} ({unit})"


def render_history_forecast_chart(
    engine: ForecastEngine,
    region_code: str,
    region_name: str,
    product: str,
    selected_year: int,
    end_year: int,
    unit: str,
) -> None:
    """Render the production timeline. Single chart, three traces: history,
    forecast, confidence band. Plus a marker for the selected year."""
    history = engine.history(region_code, product)
    if history.empty:
        st.info(
            f"{region_name} does not have meaningful "
            f"{('crude oil' if product == Product.CRUDE_OIL else 'natural gas')} "
            f"production in EIA data."
        )
        return

    fig = go.Figure()

    # History (solid).
    fig.add_trace(
        go.Scatter(
            x=history["year"],
            y=history["value"],
            mode="lines+markers",
            name="Historical",
            line=dict(color=_HISTORY_COLOR, width=3),
            marker=dict(size=6),
            hovertemplate="<b>%{x}</b><br>%{y:,.0f}<extra>Historical</extra>",
        )
    )

    # Forecast curve out to end_year (dashed).
    fc_df = engine.forecast_range(region_code, product, end_year=end_year)
    if not fc_df.empty:
        # Prepend last history point so the forecast line connects visually.
        last_year = int(history["year"].iloc[-1])
        last_value = float(history["value"].iloc[-1])
        bridge = pd.DataFrame(
            {
                "year": [last_year],
                "value": [last_value],
                "lower": [last_value],
                "upper": [last_value],
            }
        )
        plot_df = pd.concat(
            [bridge, fc_df[["year", "value", "lower", "upper"]]], ignore_index=True
        )

        # Confidence band (fill between upper and lower).
        fig.add_trace(
            go.Scatter(
                x=list(plot_df["year"]) + list(plot_df["year"][::-1]),
                y=list(plot_df["upper"]) + list(plot_df["lower"][::-1]),
                fill="toself",
                fillcolor=_BAND_COLOR,
                line=dict(color="rgba(0,0,0,0)"),
                hoverinfo="skip",
                showlegend=True,
                name="95% confidence",
            )
        )

        fig.add_trace(
            go.Scatter(
                x=plot_df["year"],
                y=plot_df["value"],
                mode="lines+markers",
                name="Forecast",
                line=dict(color=_FORECAST_COLOR, width=3, dash="dash"),
                marker=dict(size=6),
                hovertemplate="<b>%{x}</b><br>%{y:,.0f}<extra>Forecast</extra>",
            )
        )

    # Industry-context event annotations (faint vertical lines + labels
    # for years like 2014/2020/2022). Helps non-domain users see why a
    # dip / spike happened. Only drawn when the event year is in range.
    x_min = int(history["year"].min())
    x_max = int(history["year"].max())
    if not fc_df.empty:
        x_max = max(x_max, int(fc_df["year"].max()))
    for event_year, event_label in _EVENT_ANNOTATIONS:
        if x_min <= event_year <= x_max:
            fig.add_vline(
                x=event_year,
                line_width=1,
                line_dash="dot",
                line_color="rgba(255,255,255,0.25)",
                annotation_text=event_label,
                annotation_position="bottom",
                annotation=dict(
                    font=dict(size=9, color="rgba(255,255,255,0.55)"),
                    yshift=6,
                ),
            )

    # Vertical marker at the selected year.
    fig.add_vline(
        x=selected_year,
        line_width=1,
        line_dash="dot",
        line_color="#FAFAFA",
        opacity=0.5,
        annotation_text=f"Selected: {selected_year}",
        annotation_position="top",
    )

    fig.update_layout(
        title=f"{region_name} — annual production",
        xaxis_title="Year",
        yaxis_title=_y_axis_label(product, unit),
        height=420,
        margin=dict(l=10, r=10, t=60, b=40),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.02)",
    )

    st.plotly_chart(fig, use_container_width=True)
