# U.S. Oil & Gas Production Intelligence

**🌐 Live demo:** **<https://energy-platform.streamlit.app/>**

**🎥 Walkthrough video:** **<https://www.loom.com/share/18bd239ad8de45008d0fcaddc048d79e>**

A 5-tab Streamlit dashboard that helps a business-development analyst evaluate U.S. oil-and-gas production opportunities by region, with grounded AI analysis on top.

> **Submission for the CDF Energy AI Hackathon (April 2026).** Python, Streamlit, EIA's API, and Gemini 2.5 Flash.

---

## What it does

**Five tabs, one cohesive analytical story.**

### 📊 Overview tab — single-region deep-dive
- Sidebar selector for any region (national, 5 PADDs, Federal Offshore Gulf of Mexico, all 50 states + DC) and any year (2010 → 2030 forecast horizon).
- 4 KPI cards: Projected Production Estimate, YoY Growth, 5-yr CAGR, Volatility — all sourced and formula-documented in an inline expander.
- Revenue Potential powered by live WTI + Henry Hub spot prices from EIA (falls back to constants if the live feed fails).
- History + forecast chart with 95% confidence band, vertical "selected year" marker, and industry-event annotations (2014 oil-price collapse, 2020 COVID, 2022 OPEC+ recovery) so non-domain users can read the chart at a glance.
- Excel export with KPI cells as live formulas (edit a historical value in the workbook → KPIs recompute).
- 1D sensitivity slider plus a 2D scenario heatmap (volume ±30% × price ±30% → revenue, color-coded red→green).
- Three integrated AI features (all on-demand):
  - 📝 Auto-summary — narrative analyst commentary.
  - 🚨 Anomaly detection — statistical z-score flagging + LLM narrative.
  - 💬 Conversational analyst — chat with function calling, with a "Show grounding" expander that audits every numeric token.

### 🆚 Compare regions tab — multi-region comparison
- Pick 2–5 regions to overlay on one chart. Each region gets a distinct color from a color-blind-friendly palette; history is solid, forecast is dashed.
- Side-by-side KPI table with Production, YoY, 5-yr CAGR, Volatility, Revenue (USD B). Sorted descending by production.
- Default seeded with the top-5 most recent producers.

### 🗺️ Map tab — U.S. choropleth
- Plotly choropleth colored by production for the chosen product/year.
- Top-15 producers table next to the map (includes national, PADDs, GoM offshore — entities that can't appear on a state-level map).
- Forecast values render the same way and are flagged as 🔮 in the table.

### 🎯 Recommendations tab — AI-ranked top opportunities
- Composite opportunity score: `1.0·z(scale) + 1.5·z(5yr-CAGR) − 1.0·z(volatility) + 0.5·z(acceleration)`, robust z-score for outlier resistance.
- Filters out aggregate regions (national, PADDs) and tiny-base producers (< 0.5% of US national) so the ranking is BD-meaningful.
- Top-5 cards with a Gemini-generated rationale per region — caveats included.
- Full ranking expandable for transparency.

### 🔬 About & methodology tab
- Live data provenance: source URLs, series codes, cache freshness, live-price status.
- Walk-forward forecast accuracy backtest: per-region MAPE table and drill-down chart showing actual vs walk-forward predicted. Median MAPE in single-digit percent across crude regions.
- Methodology pointers to architecture.md, KPI definitions, and forecast engine source.

### Always visible — at-a-glance header strip
- U.S. national crude + gas with YoY direction
- Live WTI + Henry Hub prices with as-of date

For non-producing regions (Vermont, Hawaii, Rhode Island, etc.), the Overview tab surfaces a friendly empty state suggesting top producers — instead of hiding regions or showing zero-filled charts.

---

## Quickstart (local)

```bash
git clone https://github.com/Community-Dreams-Foundation-Hackathons/energy-intelligence-system-vivekyagnikms.git
cd energy-intelligence-system-vivekyagnikms

python -m venv .venv
source .venv/Scripts/activate    # Windows bash; use .venv/bin/activate on Linux/macOS
pip install -r requirements.txt

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
| [`streamlit_app.py`](streamlit_app.py) | Entry point + tab dispatch. |
| [`src/data/`](src/data/) | EIA client, production loader, **live-price feed**, region registry, schema. |
| [`src/forecast/`](src/forecast/) | Linear-regression engine + **walk-forward backtester**. |
| [`src/kpis/`](src/kpis/) | All KPI calculators as pure functions. |
| [`src/ai/`](src/ai/) | Gemini client, function-calling tools, chat loop, summary, anomaly, **recommendation engine**, mock fallback. |
| [`src/ui/`](src/ui/) | Sidebar, **header strip**, KPI cards, chart, tools panel, AI chat panel, **map view, compare view, recommendations view, about view**. |
| [`src/utils/`](src/utils/) | Cache, Excel export with formulas, input sanitization. |
| [`tests/`](tests/) | Hermetic test suite, runs in <4 seconds. |
| [`planning/planning.md`](planning/planning.md) | Pre-build planning document. |
| [`docs/brd.md`](docs/brd.md) | Business Requirements Document — stakeholders, business problem, objectives, scope. |
| [`docs/prd.md`](docs/prd.md) | Product Requirements Document — personas, user stories, features, non-functional requirements. |
| [`docs/tdd.md`](docs/tdd.md) | Technical Design Document — data model, API contracts, components, deployment, runbook. |
| [`docs/architecture.md`](docs/architecture.md) | Architecture summary; data flow; AI guardrail layers. |
| [`docs/kpi_definitions.md`](docs/kpi_definitions.md) | Every KPI's formula, unit, edge cases. |
| [`docs/insights.md`](docs/insights.md) | Decision-grade insights surfaced by the system. |
| [`docs/walkthrough.md`](docs/walkthrough.md) | Walkthrough video link and script. |

---

## Tech stack

Python 3.14 · Streamlit 1.56 · pandas · scikit-learn · Plotly (Express + Graph Objects) · `google-genai` (Gemini 2.5 Flash) · Pydantic 2 · openpyxl · pytest · ruff. Live deploy on Streamlit Community Cloud.

---

## How AI is integrated (and why you can trust the numbers)

**Core principle: deterministic code computes; the LLM phrases.**

The LLM never produces a number from training knowledge. It calls one of six tools (`get_production`, `get_history`, `compare_regions`, `get_kpis`, `get_anomalies`, `list_regions`) which operate on the same in-memory DataFrame the UI is showing. Every numeric token in the LLM's final answer is regex-extracted and cross-checked against tool-returned values within ±1%; mismatches are flagged as ⚠ Unverified in the UI.

The recommendation engine takes the same approach one level up: a deterministic composite score ranks every region; the LLM only narrates the top-N and **cannot reorder, add, or remove regions**.

13 guardrail layers in total — see [`docs/architecture.md`](docs/architecture.md#guardrail-layers-13-total) for the full list.

When the Gemini free tier (5 RPM / 25 RPD on `gemini-2.5-flash`) is exhausted during a demo, a circuit breaker swaps to mock-mode responses with a visible badge. The demo never hard-fails.

---

## Forecast accuracy (walk-forward backtest)

Per-region MAPE figures are visible live on the **About & methodology** tab. The backtest re-runs the linear-regression model as if every historical year were unknown — train on data up through year Y−1, predict Y, compare to actual. Aggregated results across stable regions (PADD 5 West Coast, Alaska, PADD 3 Gulf Coast, United States national) sit in the single-digit percent range; high-volatility regions (e.g., North Dakota) show wider error bands as expected for linear models.

---

## Tests

```bash
pytest -q
```

Hermetic test suite (no live EIA / Gemini calls), runs in <4 seconds. Coverage spans data normalization, forecast engine math + edges, backtester, every KPI, AI tool router, AI regression with adversarial prompts, recommendation engine, live-price fallback contract, security input + log redaction, full-pipeline integration, and end-to-end import smoke.

---

## AI tools used during development

Claude (Anthropic) was used as a coding assistant for scaffolding, schema generation, test drafting, and documentation drafts (with human review). API keys were never visible to the AI assistant; they live in `.streamlit/secrets.toml` (gitignored) locally and in Streamlit Cloud's secrets manager in production.

---

## License

[MIT](LICENSE).
