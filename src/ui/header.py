"""At-a-glance header strip. Sits above the tabs and shows national context
regardless of the user's current selection — production scale, YoY direction,
data freshness, live commodity prices."""

from __future__ import annotations


import pandas as pd
import streamlit as st

from src.data.prices import CommodityPrices
from src.kpis.calculators import yoy_growth_rate


def _fmt_volume_short(value: float, unit: str) -> str:
    if unit.upper() == "MBBL":
        return f"{value / 1_000_000:.2f}B bbl"
    if unit.upper() == "MMCF":
        return f"{value / 1_000_000:.2f} Tcf"
    return f"{value:,.0f} {unit}"


def render_header(df: pd.DataFrame, prices: CommodityPrices) -> None:
    """Page-level summary strip. Always shows US national context."""
    if df.empty:
        return

    last_full_year = (
        int(df.loc[df["n_months"] >= 12, "year"].max())
        if (df["n_months"] >= 12).any()
        else int(df["year"].max())
    )

    nus_crude = df[
        (df["region_code"] == "NUS")
        & (df["product"] == "crude_oil")
        & (df["year"] == last_full_year)
    ]
    nus_gas = df[
        (df["region_code"] == "NUS")
        & (df["product"] == "natural_gas")
        & (df["year"] == last_full_year)
    ]

    crude_value = float(nus_crude["value"].iloc[0]) if not nus_crude.empty else None
    gas_value = float(nus_gas["value"].iloc[0]) if not nus_gas.empty else None

    crude_yoy = yoy_growth_rate(df, "NUS", "crude_oil", last_full_year)
    gas_yoy = yoy_growth_rate(df, "NUS", "natural_gas", last_full_year)

    c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 2])

    with c1:
        st.metric(
            label=f"🇺🇸 U.S. crude — {last_full_year}",
            value=_fmt_volume_short(crude_value, "MBBL") if crude_value else "—",
            delta=f"{crude_yoy * 100:+.1f}% YoY" if crude_yoy is not None else None,
        )
    with c2:
        st.metric(
            label=f"🔥 U.S. natural gas — {last_full_year}",
            value=_fmt_volume_short(gas_value, "MMCF") if gas_value else "—",
            delta=f"{gas_yoy * 100:+.1f}% YoY" if gas_yoy is not None else None,
        )
    with c3:
        wti_label = "Live" if prices.is_live else "Default"
        st.metric(
            label=f"🛢️ WTI ({wti_label})",
            value=f"USD {prices.wti_usd_per_bbl:.2f}/bbl",
            help=prices.wti_label,
        )
    with c4:
        hh_label = "Live" if prices.is_live else "Default"
        st.metric(
            label=f"⛽ Henry Hub ({hh_label})",
            value=f"USD {prices.henry_hub_usd_per_mmbtu:.2f}/MMBtu",
            help=prices.henry_hub_label,
        )
    with c5:
        as_of = prices.as_of if prices.is_live and prices.as_of else "—"
        st.metric(
            label="📅 Prices as of",
            value=as_of,
            help=(
                "Date of the most recent EIA spot-price reading. Live values "
                "feed Revenue Potential KPI on the Overview tab."
                if prices.is_live
                else "Live prices unavailable — Revenue Potential uses "
                "illustrative constants (WTI USD 75/bbl, Henry Hub USD 3/MMBtu)."
            ),
        )
