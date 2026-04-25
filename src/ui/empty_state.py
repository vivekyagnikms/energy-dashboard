"""Empty-state component shown when a region has no oil/gas production."""
from __future__ import annotations

import streamlit as st

from src.data.regions import Region
from src.data.schema import Product

# Suggested top producers for redirecting users from non-producing regions.
TOP_CRUDE_PRODUCERS: tuple[str, ...] = ("Texas", "North Dakota", "New Mexico", "Oklahoma", "Colorado")
TOP_GAS_PRODUCERS: tuple[str, ...] = ("Texas", "Pennsylvania", "Louisiana", "West Virginia", "Ohio")


def render_empty_state(region: Region, product: str) -> None:
    """Friendly message for a region that does not produce the selected product."""
    pretty_product = "crude oil" if product == Product.CRUDE_OIL else "natural gas"
    suggestions = TOP_CRUDE_PRODUCERS if product == Product.CRUDE_OIL else TOP_GAS_PRODUCERS

    st.info(
        f"📭 **{region.name}** does not have meaningful "
        f"{pretty_product} production in EIA data."
    )
    st.markdown(
        f"Try a major {pretty_product} producer instead: "
        + ", ".join(f"**{s}**" for s in suggestions[:3])
        + "."
    )
