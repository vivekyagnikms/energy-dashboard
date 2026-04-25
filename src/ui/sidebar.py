"""Sidebar: region, product, year selectors. Single source of user intent.

Returns a Selection dataclass that the rest of the UI consumes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
import streamlit as st

from src.data.regions import (
    ALL_REGIONS,
    Region,
    RegionGroup,
)
from src.data.schema import Product

# Regions selectable in the dropdown. Sorted by group then alphabetically.
_GROUP_LABELS: dict[RegionGroup, str] = {
    RegionGroup.NATIONAL: "United States",
    RegionGroup.OFFSHORE: "Federal Offshore",
    RegionGroup.PADD: "PADD (regional groupings)",
    RegionGroup.STATE: "States",
}


@dataclass(frozen=True)
class Selection:
    region: Region
    product: str
    year: int


def _format_region(region: Region) -> str:
    """Human-readable label with a group hint prefix for the dropdown."""
    if region.group is RegionGroup.NATIONAL:
        return f"🇺🇸  {region.name}"
    if region.group is RegionGroup.OFFSHORE:
        return f"🌊  {region.name}"
    if region.group is RegionGroup.PADD:
        return f"🗺️  {region.name}"
    return f"📍  {region.name}"


def _ordered_regions() -> list[Region]:
    """Display order: national, offshore, PADDs, then states alphabetically."""
    by_group: dict[RegionGroup, list[Region]] = {}
    for r in ALL_REGIONS:
        by_group.setdefault(r.group, []).append(r)
    out: list[Region] = []
    for group in (
        RegionGroup.NATIONAL,
        RegionGroup.OFFSHORE,
        RegionGroup.PADD,
        RegionGroup.STATE,
    ):
        items = sorted(
            by_group.get(group, []),
            key=lambda r: r.sort_priority * 1000 + ord(r.name[0]),
        )
        if group is RegionGroup.STATE:
            items = sorted(by_group.get(group, []), key=lambda r: r.name)
        out.extend(items)
    return out


def render_sidebar(df: pd.DataFrame) -> Selection:
    """Render the sidebar and return the user's current selection.

    `df` is the canonical annual DataFrame; used to size the year slider's
    valid range from the data the app actually has.
    """
    st.sidebar.title("⚡ Energy Intelligence")
    st.sidebar.caption("U.S. Oil & Gas Production Analytics")
    st.sidebar.divider()

    # --- Region ---
    regions = _ordered_regions()
    default_idx = next(
        (i for i, r in enumerate(regions) if r.group is RegionGroup.NATIONAL), 0
    )
    region = st.sidebar.selectbox(
        "Region",
        options=regions,
        index=default_idx,
        format_func=_format_region,
        help="Includes US national, 5 PADDs, Federal Offshore Gulf of Mexico, "
        "and all 50 states + DC. States with no oil/gas production show a "
        "clean empty state when selected.",
    )

    # --- Product ---
    product_label = st.sidebar.radio(
        "Product",
        options=("Crude Oil", "Natural Gas"),
        horizontal=True,
        help="Switch the analytical view between the two products.",
    )
    product = Product.CRUDE_OIL if product_label == "Crude Oil" else Product.NATURAL_GAS

    # --- Year ---
    # Slider runs from earliest year in the data to (latest year + 5) so the
    # user can sweep across past actuals into forecast territory.
    if df.empty:
        min_year, latest_observed = 2010, date.today().year - 1
    else:
        min_year = int(df["year"].min())
        full_years = df.loc[df["n_months"] >= 12, "year"]
        latest_observed = (
            int(full_years.max()) if not full_years.empty else int(df["year"].max())
        )
    max_year = latest_observed + 5
    year = st.sidebar.slider(
        "Year",
        min_value=min_year,
        max_value=max_year,
        value=latest_observed,
        step=1,
        help=(
            f"Historical actuals go up to {latest_observed}. "
            f"Anything beyond that is a forecast."
        ),
    )

    # --- Visual cue: forecast vs actual ---
    if year > latest_observed:
        st.sidebar.warning(f"📈 {year} is a forecast (last actual: {latest_observed}).")
    else:
        st.sidebar.success(f"📊 {year} is historical data.")

    st.sidebar.divider()

    # --- Refresh ---
    if st.sidebar.button(
        "🔄 Refresh data from EIA",
        help="Force a live re-fetch from the EIA API. Bypasses the 24h parquet cache.",
        use_container_width=True,
    ):
        st.cache_data.clear()
        st.toast("Cleared cache — refetching from EIA…", icon="🔄")
        st.rerun()

    st.sidebar.divider()

    # --- About ---
    with st.sidebar.expander("ℹ️  About this dashboard"):
        st.markdown(
            """
            **Source:** U.S. Energy Information Administration (EIA) API v2 — live
            crude-oil field production and natural-gas marketed production.

            **Forecast:** linear regression on annual full-year totals;
            ±95% confidence band from residual standard deviation.

            **AI:** grounded in tool calls against the same data shown on screen.
            """
        )

    return Selection(region=region, product=product, year=int(year))
