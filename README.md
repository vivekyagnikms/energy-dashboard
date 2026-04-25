# U.S. Oil & Gas Production Intelligence

**Live demo:** _add Streamlit Cloud URL here after deploy_

A single-page Streamlit dashboard that helps a business-development analyst evaluate U.S. oil-and-gas production opportunities by region, with grounded AI analysis on top.

> **Submission for the CDF Energy AI Hackathon (April 2026).** Built in one day on Python, Streamlit, EIA's API, and Gemini 2.5 Flash. All Tier-1 requirements + three Tier-2 differentiators shipped.

---

## What it does

For any U.S. region (national, 5 PADDs, Federal Offshore Gulf of Mexico, all 50 states + DC) and any year (2010 → 2030 forecast horizon), the dashboard surfaces:

- **Required KPI: Projected Production Estimate** — actual EIA value for past full years, linear-regression forecast for future or partial-current years.
- **Custom KPIs:** YoY Growth Rate, 5-year CAGR, Production Volatility, illustrative Revenue Potential.
- **Interactive chart** — solid history + dashed forecast + 95% confidence band + "selected year" marker.
- **Three integrated AI features** (all on-demand to conserve free-tier quota):
  - 📝 Auto-summary — narrative commentary grounded on the same data shown on screen.
  - 🚨 Anomaly detection — statistical z-score flagging + LLM narrative explanation.
  - 💬 Conversational analyst — chat with function calling against the live data, with a "Show grounding" expander revealing every tool call.
- **Excel export** with KPI cells as live formulas (edit a historical value in the workbook → KPIs recompute).
- **Sensitivity slider** — stress-test forecast assumptions ±30%.
- **Provenance popover** — source URL, fetch timestamp, coverage stats.

For non-producing regions (Vermont, Hawaii, Rhode Island, etc.), the app surfaces a friendly empty state suggesting top producers — instead of hiding the regions or showing zero-filled charts.

---

## Quickstart (local)

```bash
git clone https://github.com/Community-Dreams-Foundation-Hackathons/energy-intelligence-system-vivekyagnikms.git
cd energy-intelligence-system-vivekyagnikms

python -m venv .venv
source .venv/Scripts/activate    # Windows bash; use .venv/bin/activate on Linux/macOS
pip install -r requirements.txt

# Set up secrets
cp .streamlit/secrets.toml.example .streamlit/secrets.toml  # then fill in your keys
#   EIA_API_KEY:    free at https://www.eia.gov/opendata/register.php
#   GEMINI_API_KEY: free at https://aistudio.google.com/apikey

streamlit run streamlit_app.py
```

The app opens at <http://localhost:8501>. First fetch from EIA takes ~10 seconds; subsequent loads use the parquet cache (24h TTL).

---

## Repo map

| Path | Contents |
|---|---|
| [`streamlit_app.py`](streamlit_app.py) | Entry point. |
| [`src/data/`](src/data/) | EIA client, loader, region registry, schema. |
| [`src/forecast/`](src/forecast/) | Linear-regression forecast engine with insufficient-data + horizon guards. |
| [`src/kpis/`](src/kpis/) | All KPI calculators as pure functions. |
| [`src/ai/`](src/ai/) | Gemini client, function-calling tools, chat loop, summary, anomaly, mock fallback. |
| [`src/ui/`](src/ui/) | Sidebar, KPI cards, chart, tools panel, AI chat panel, empty state. |
| [`src/utils/`](src/utils/) | Cache, Excel export with formulas, input sanitization. |
| [`tests/`](tests/) | 73 hermetic tests, runs in <3 seconds. |
| [`planning/planning.md`](planning/planning.md) | Pre-build plan (judges compare this against the final state). |
| [`docs/architecture.md`](docs/architecture.md) | Final architecture; data flow; 13 AI guardrails. |
| [`docs/kpi_definitions.md`](docs/kpi_definitions.md) | Every KPI's formula, unit, edge cases. |
| [`docs/walkthrough.md`](docs/walkthrough.md) | 5-minute video link + script. |
| [`docs/reflection.md`](docs/reflection.md) | Honest post-build retrospective. |

---

## Tech stack at a glance

Python 3.14 · Streamlit 1.56 · pandas · scikit-learn · Plotly · `google-genai` (Gemini 2.5 Flash) · Pydantic 2 · openpyxl · pytest · ruff. Live deploy on Streamlit Community Cloud.

---

## How AI is integrated (and why you can trust the numbers)

**Core principle: deterministic code computes; the LLM phrases.**

The LLM never produces a number from training knowledge. It calls one of six tools (`get_production`, `get_history`, `compare_regions`, `get_kpis`, `get_anomalies`, `list_regions`) which operate on the same in-memory DataFrame the UI is showing. Every numeric token in the LLM's final answer is regex-extracted and cross-checked against tool-returned values within ±1%; mismatches are flagged as ⚠ Unverified in the UI.

13 layers of guardrails total — see [`docs/architecture.md`](docs/architecture.md#guardrail-layers-13-total) for the full list.

When the Gemini free tier (5 RPM / 25 RPD on `gemini-2.5-flash`) is exhausted during a demo, a circuit breaker swaps to mock-mode responses with a visible badge. The demo never hard-fails.

---

## Tests

```bash
pytest -q
```

73 tests, all hermetic (no live EIA / Gemini calls), runs in 2.8 seconds. Coverage: data loader normalization, forecast engine math + edges, every KPI, AI tool router, AI regression suite (mock-mode + adversarial prompts), security input sanitization, full-pipeline integration, end-to-end import smoke.

---

## License

[MIT](LICENSE).
