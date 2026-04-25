"""AI panel: auto-summary, anomaly explainer, conversational analyst.

Uses st.session_state to hold chat history and a per-session message cap.
Every AI response includes a 'Show grounding' expander listing the tools
that were called and what they returned — judges (and curious users) can
audit any number on screen.
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from src.ai.anomaly import AnomalyResult, explain_anomalies
from src.ai.chat import ChatTurnResult, run_chat_turn
from src.ai.client import GeminiClient
from src.ai.summarize import SummaryResult, summarize_region
from src.forecast.engine import ForecastEngine

# Per-session caps. Keep the chat conversation focused and protect free-tier
# quota during judging.
MAX_USER_INPUT_CHARS: int = 2000
MAX_MESSAGES_PER_SESSION: int = 30


def _ensure_session_state() -> None:
    if "chat_history" not in st.session_state:
        # Each entry: {'role': 'user'|'assistant', 'text': str,
        #              'tool_calls': list[ToolCallRecord], 'flags': dict}
        st.session_state["chat_history"] = []
    if "message_count" not in st.session_state:
        st.session_state["message_count"] = 0


def _render_grounding(turn: ChatTurnResult | None) -> None:
    """Expander showing what tools were called and what they returned."""
    if not turn:
        return
    if not turn.tool_calls and not turn.is_mock and not turn.is_refusal:
        return
    with st.expander("🔍 Show grounding (tool calls + raw outputs)"):
        if turn.is_mock:
            st.warning(
                "This response came from mock-mode (live AI rate-limited / disabled)."
            )
        if turn.is_refusal:
            st.info("Refusal response — request was off-topic.")
        if turn.unverified_numbers:
            st.warning(
                "⚠️ Unverified figures in this answer: "
                + ", ".join(f"`{n}`" for n in turn.unverified_numbers)
                + ". These numbers were not directly returned by any tool call this turn."
            )
        for i, rec in enumerate(turn.tool_calls, start=1):
            st.markdown(f"**Call {i}: `{rec.name}`**")
            st.code(json.dumps(rec.args, indent=2, default=str), language="json")
            st.code(json.dumps(rec.result, indent=2, default=str), language="json")


def _render_summary(summary: SummaryResult) -> None:
    badge = "🤖 Mock" if summary.is_mock else "🧠 AI"
    confidence_color = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(
        summary.confidence, "⚪"
    )
    st.markdown(f"**{badge} · {confidence_color} Confidence: {summary.confidence}**")
    st.markdown(summary.summary)
    if summary.top_drivers:
        st.markdown("**Top drivers:**")
        for d in summary.top_drivers:
            st.markdown(f"- {d}")
    if summary.caveats:
        with st.expander("⚠️ Caveats"):
            for c in summary.caveats:
                st.markdown(f"- {c}")


def _render_anomalies(report: AnomalyResult) -> None:
    badge = "🤖 Mock" if report.is_mock else "🧠 AI"
    st.markdown(f"**{badge} · {report.region} · {report.product}**")
    st.caption(f"Method: {report.method}")
    if report.note:
        st.info(report.note)
    if not report.explanations:
        return
    df = pd.DataFrame(report.explanations)
    st.dataframe(
        df[["year", "yoy_pct", "z_score", "explanation"]],
        column_config={
            "year": "Year",
            "yoy_pct": st.column_config.NumberColumn("YoY %", format="%+.1f%%"),
            "z_score": st.column_config.NumberColumn("Z-score", format="%.2f"),
            "explanation": "Narrative",
        },
        hide_index=True,
        use_container_width=True,
    )


def render_ai_panel(
    client: GeminiClient,
    df: pd.DataFrame,
    engine: ForecastEngine,
    region_code: str,
    region_name: str,
    product: str,
    selected_year: int,
    is_supported: bool,
) -> None:
    """The whole AI section. Three on-demand features so we don't burn quota on
    every region/year change."""
    _ensure_session_state()

    st.subheader("🧠 AI Analyst")

    if not is_supported:
        st.caption(
            "AI features are disabled for non-producing regions. Pick a major "
            "producer (e.g. Texas, North Dakota) to enable analysis."
        )
        return

    # --- Three feature buttons in a row ---
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button(
            "📝 Auto-summary",
            help="Narrative commentary on the selected region/year",
            use_container_width=True,
            key="btn_summary",
        ):
            with st.spinner("Generating summary…"):
                summary = summarize_region(
                    client, df, engine, region_code, product, selected_year
                )
                st.session_state["last_summary"] = summary
    with c2:
        if st.button(
            "🚨 Detect anomalies",
            help="Statistical anomaly detection + narrative explanation",
            use_container_width=True,
            key="btn_anomaly",
        ):
            with st.spinner("Detecting anomalies…"):
                anomaly = explain_anomalies(client, df, engine, region_code, product)
                st.session_state["last_anomaly"] = anomaly
    with c3:
        st.caption("Chat with the data ↓")

    # --- Render last summary / anomaly if produced ---
    if st.session_state.get("last_summary"):
        with st.container(border=True):
            _render_summary(st.session_state["last_summary"])
    if st.session_state.get("last_anomaly"):
        with st.container(border=True):
            _render_anomalies(st.session_state["last_anomaly"])

    st.divider()

    # --- Conversational analyst ---
    st.markdown("**💬 Conversational analyst**")
    st.caption(
        f"Ask about any region, product, year, or comparison. "
        f"Session messages: {st.session_state['message_count']}/{MAX_MESSAGES_PER_SESSION}. "
        f"Inputs are capped at {MAX_USER_INPUT_CHARS} chars."
    )

    # Replay history.
    for msg in st.session_state["chat_history"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["text"])
            if msg["role"] == "assistant" and msg.get("turn"):
                _render_grounding(msg["turn"])

    # Input.
    if st.session_state["message_count"] >= MAX_MESSAGES_PER_SESSION:
        st.warning(
            f"You have reached the session message cap ({MAX_MESSAGES_PER_SESSION}). "
            "Refresh the page to start a new session."
        )
        return

    user_msg = st.chat_input(
        "Ask about production trends, forecasts, comparisons, anomalies…"
    )
    if not user_msg:
        return
    user_msg = user_msg.strip()[:MAX_USER_INPUT_CHARS]
    if not user_msg:
        return

    st.session_state["message_count"] += 1
    st.session_state["chat_history"].append(
        {"role": "user", "text": user_msg, "turn": None}
    )

    with st.chat_message("user"):
        st.markdown(user_msg)

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            turn = run_chat_turn(
                client,
                df,
                engine,
                user_msg,
                history=[
                    {
                        "role": h["role"] if h["role"] != "assistant" else "model",
                        "text": h["text"],
                    }
                    for h in st.session_state["chat_history"][:-1]
                    if h.get("turn") is None or not h["turn"].is_mock
                ][-6:],  # short history window to keep prompts small
            )
        st.markdown(turn.text)
        _render_grounding(turn)

    st.session_state["chat_history"].append(
        {"role": "assistant", "text": turn.text, "turn": turn}
    )
