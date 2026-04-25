"""KPI card row. Renders the four headline numbers + revenue potential."""

from __future__ import annotations

import streamlit as st

from src.data.schema import Product
from src.kpis.calculators import KPISet


def _fmt_volume(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit.upper() == "MBBL":
        # MBBL = thousand barrels. Use B (billion bbl) for >=1bn, else M (million bbl).
        billions = value / 1_000_000
        if billions >= 1:
            return f"{billions:.2f}B bbl"
        millions = value / 1_000
        return f"{millions:.1f}M bbl"
    if unit.upper() == "MMCF":
        # MMCF = million cubic feet. Use Tcf for >=1tn cf, else Bcf.
        tcf = value / 1_000_000
        if tcf >= 1:
            return f"{tcf:.2f} Tcf"
        bcf = value / 1_000
        return f"{bcf:.1f} Bcf"
    return f"{value:,.0f} {unit}"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:+.1f}%"


def _fmt_ratio(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}"


def _fmt_usd(value: float | None) -> str:
    """USD-prefixed money string. Avoids '$' so Streamlit's KaTeX renderer
    does not silently consume currency values as math delimiters."""
    if value is None:
        return "—"
    if value >= 1_000_000_000:
        return f"USD {value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"USD {value / 1_000_000:.1f}M"
    return f"USD {value:,.0f}"


def render_kpi_cards(kpis: KPISet) -> None:
    """Top KPI row + a smaller revenue-potential strip below."""
    forecast_badge = "🔮 Forecast" if kpis.is_forecast else "📊 Actual"
    product_label = "Crude Oil" if kpis.product == Product.CRUDE_OIL else "Natural Gas"

    st.subheader(f"{kpis.region_name} · {product_label} · {kpis.year}")
    st.caption(f"{forecast_badge}")

    # Wider first column for the headline KPI; narrower for the trio of
    # secondary metrics. Prevents the projected-production value from
    # truncating to "4.96..." when the value is in billions.
    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
    with col1:
        st.metric(
            label="Projected Production",
            value=_fmt_volume(
                kpis.projected_production, kpis.projected_production_unit
            ),
            help="Headline KPI. Past full years use EIA actuals; future and "
            "partial-current years use a linear-regression forecast.",
        )
    with col2:
        st.metric(
            label="YoY Growth",
            value=_fmt_pct(kpis.yoy_growth_rate),
            help="Year-over-year percent change. Only computed for years that "
            "have a directly observed prior year.",
        )
    with col3:
        st.metric(
            label="5-yr CAGR",
            value=_fmt_pct(kpis.five_year_cagr),
            help="Compound annual growth rate over the 5 years ending in the "
            "selected year. Smooths cyclical noise.",
        )
    with col4:
        st.metric(
            label="Volatility",
            value=_fmt_ratio(kpis.volatility),
            help="Coefficient of variation of YoY % over the trailing 10 years. "
            "Higher = more boom/bust risk.",
        )

    # We avoid '$' anywhere in this string: Streamlit pipes captions through
    # KaTeX, which consumes unmatched dollar signs as math-mode delimiters.
    if kpis.revenue_price_label:
        st.caption(
            f"**Revenue Potential:** {_fmt_usd(kpis.revenue_potential_usd)} "
            f" — at {kpis.revenue_price_label}."
        )
    else:
        st.caption(
            f"**Revenue Potential (illustrative):** {_fmt_usd(kpis.revenue_potential_usd)} "
            f" — at WTI USD 75/bbl or Henry Hub USD 3.00/MMBtu. "
            f"*Not a live price feed.*"
        )

    if kpis.notes:
        for note in kpis.notes:
            st.info(note)

    # Source/formula panel — links every KPI back to its source code +
    # exact formula. Closed by default so it doesn't clutter the page.
    with st.expander("ℹ️  How are these computed? (formulas + source)"):
        st.markdown(
            """
| KPI | Formula | Code |
|---|---|---|
| **Projected Production** | Actual EIA value if past full year, else linear-regression forecast | [`kpis/calculators.py::get_actual_or_forecast`](https://github.com/Community-Dreams-Foundation-Hackathons/energy-intelligence-system-vivekyagnikms/blob/main/src/kpis/calculators.py) |
| **YoY Growth** | `(value[y] − value[y−1]) / value[y−1]` | [`yoy_growth_rate`](https://github.com/Community-Dreams-Foundation-Hackathons/energy-intelligence-system-vivekyagnikms/blob/main/src/kpis/calculators.py) |
| **5-yr CAGR** | `(value[y] / value[y−5])^(1/5) − 1` | [`five_year_cagr`](https://github.com/Community-Dreams-Foundation-Hackathons/energy-intelligence-system-vivekyagnikms/blob/main/src/kpis/calculators.py) |
| **Volatility** | `stdev(YoY%) / |mean(YoY%)|` over trailing 10 years | [`volatility`](https://github.com/Community-Dreams-Foundation-Hackathons/energy-intelligence-system-vivekyagnikms/blob/main/src/kpis/calculators.py) |
| **Revenue Potential** | `volume × price` (live WTI / Henry Hub if available, else illustrative constant) | [`revenue_potential_usd`](https://github.com/Community-Dreams-Foundation-Hackathons/energy-intelligence-system-vivekyagnikms/blob/main/src/kpis/calculators.py) |

Full definitions in [`docs/kpi_definitions.md`](https://github.com/Community-Dreams-Foundation-Hackathons/energy-intelligence-system-vivekyagnikms/blob/main/docs/kpi_definitions.md).

**Source data:** EIA API v2 — `petroleum/crd/crpdn` (crude, MBBL) and
`natural-gas/prod/sum` (gas, MMCF). Aggregated monthly → annual.
            """
        )
