"""End-to-end smoke test: the Streamlit script imports cleanly and the app
function exists. We do NOT spin up a real Streamlit server here — the pytest
collector cannot run inside Streamlit's runtime — but importing the module
exercises every UI module and catches syntax / import-graph errors before
they surface in a deploy."""
from __future__ import annotations


def test_streamlit_app_imports_cleanly():
    import streamlit_app  # noqa: F401

    assert callable(streamlit_app.main)


def test_all_ui_modules_import_cleanly():
    from src.ui import charts, chat_panel, empty_state, kpi_cards, sidebar, tools_panel  # noqa: F401


def test_all_ai_modules_import_cleanly():
    from src.ai import anomaly, chat, client, mock, summarize, tools  # noqa: F401


def test_all_data_modules_import_cleanly():
    from src.data import eia_client, loader, regions, schema  # noqa: F401


def test_all_forecast_kpi_utils_import_cleanly():
    from src.forecast import engine  # noqa: F401
    from src.kpis import calculators  # noqa: F401
    from src.utils import cache, excel_export, security  # noqa: F401
