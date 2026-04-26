"""Recommendations tab: AI-ranked top opportunities."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.ai.client import GeminiClient
from src.ai.recommend import recommend
from src.data.prices import CommodityPrices
from src.data.schema import Product
from src.forecast.engine import ForecastEngine


def render_recommendations_tab(
    df: pd.DataFrame,
    engine: ForecastEngine,
    prices: CommodityPrices,
    client: GeminiClient,
    selection,
) -> None:
    """Recommendation engine driven by the sidebar product. Year is display-only
    (the composite score uses the most recent full year regardless of slider)."""
    product = selection.product
    year = int(selection.year)
    product_label = "Crude Oil" if product == Product.CRUDE_OIL else "Natural Gas"

    st.header("🎯 Investment recommendations")
    st.caption(
        f"Composite opportunity score ranks every supported region for "
        f"**{product_label}**; Gemini narrates the top 5 with grounded "
        f"explanations. Score weights, score components, and full ranking are "
        f"all visible — no black boxes. Change product via the sidebar."
    )

    # ---- Trigger button (don't burn quota on every rerun) ----
    if st.button(
        "🎯 Generate top-5 recommendations",
        type="primary",
        use_container_width=True,
        key="rec_generate",
    ):
        with st.spinner("Scoring all regions and asking the analyst…"):
            report = recommend(client, df, engine, product, year)
            st.session_state["last_recommendations"] = report
            st.session_state["last_recommendations_product"] = product

    report = st.session_state.get("last_recommendations")
    if report is None:
        st.info(
            "Click the button above to compute the ranking and generate AI "
            "recommendations. (Conserves Gemini free-tier quota.)"
        )
        return

    if report.product != st.session_state.get("last_recommendations_product"):
        st.warning(
            "Product changed since last generation. Click 'Generate' again to refresh."
        )

    badge = "🤖 Mock" if report.is_mock else "🧠 AI"
    st.markdown(f"**{badge} · {len(report.recommendations)} top recommendations**")
    st.caption(report.method_note)

    # ---- Top-5 cards ----
    for rec in report.recommendations:
        with st.container(border=True):
            head_col, score_col = st.columns([4, 1])
            with head_col:
                st.markdown(f"### #{rec.rank} · {rec.region_name}")
                st.markdown(f"**{rec.headline}**")
            with score_col:
                st.metric("Score", f"{rec.score:+.2f}")
            st.markdown(rec.rationale)
            if rec.caveats:
                with st.expander("⚠️ Caveats"):
                    for c in rec.caveats:
                        st.markdown(f"- {c}")

    # ---- Full ranking (expandable) ----
    with st.expander("🔢 Full ranking (all supported regions)"):
        if not report.rows:
            st.info("No regions to rank.")
            return
        unit = "MBBL" if product == Product.CRUDE_OIL else "MMCF"
        rank_df = pd.DataFrame(
            [
                {
                    "Rank": i,
                    "Region": r.region_name,
                    "Score": r.score,
                    f"Scale ({unit})": r.scale,
                    "5yr CAGR": r.growth_5yr * 100
                    if r.growth_5yr is not None
                    else None,
                    "Volatility": r.volatility,
                    "Accel": r.acceleration * 100
                    if r.acceleration is not None
                    else None,
                }
                for i, r in enumerate(report.rows, start=1)
            ]
        )
        st.dataframe(
            rank_df,
            column_config={
                "Rank": st.column_config.NumberColumn("Rank", format="%d"),
                "Region": "Region",
                "Score": st.column_config.NumberColumn("Score", format="%+.2f"),
                f"Scale ({unit})": st.column_config.NumberColumn(
                    f"Scale ({unit})", format="%,.0f"
                ),
                "5yr CAGR": st.column_config.NumberColumn("5yr CAGR", format="%+.1f%%"),
                "Volatility": st.column_config.NumberColumn(
                    "Volatility", format="%.2f"
                ),
                "Accel": st.column_config.NumberColumn(
                    "Accel (YoY−CAGR)", format="%+.1f%%"
                ),
            },
            hide_index=True,
            use_container_width=True,
            height=400,
        )
