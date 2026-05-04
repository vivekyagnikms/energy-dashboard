# Architecture Overview

How the U.S. Oil & Gas Production Intelligence dashboard is structured: data flow, AI integration design, components, and deployment shape. Companion documents: [`brd.md`](brd.md), [`prd.md`](prd.md), [`tdd.md`](tdd.md), [`kpi_definitions.md`](kpi_definitions.md), [`case_study.md`](case_study.md).

---

## Final Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.14 | Single language end-to-end. |
| Web framework | Streamlit 1.56 + streamlit-extras | Native data-app primitives + GitHub-connected deploy. |
| Data | EIA API v2 + pandas + parquet cache | Faceted queries fetch all-region data in ~5 paginated calls per product. |
| Forecasting | scikit-learn `LinearRegression` | Explainable; `statsmodels` was held in reserve and not needed. |
| Charts | Plotly | Interactive, theme-aware, exports cleanly. |
| AI | Google Gemini 2.5 Flash via `google-genai` SDK | Free tier; native function calling + structured outputs. |
| Validation | Pydantic 2 | Tool input validation + structured AI output schema. |
| Excel export | openpyxl | Workbook with KPI cells as live formulas. |
| Testing | pytest | Hermetic test suite; runs in <4s. |
| Linting/formatting | ruff | All checks pass. |
| Deploy | Streamlit Community Cloud | One-click GitHub-connected. |
| Secrets | `.streamlit/secrets.toml` (gitignored) + Streamlit Cloud secrets | Standard pattern. |

**Notable design choices:**

- **AI model: `gemini-2.5-flash`** via the `google-genai` SDK. Free tier with native function calling and structured outputs (`response_schema`). `MODEL_FALLBACKS` in `src/ai/client.py` documents alternatives if quota or availability changes for a future deploy.
- **Region coverage:** all 50 states + DC + 5 PADDs + Federal Offshore Gulf of Mexico + U.S. national. Single faceted EIA query per product fetches the full set.
- **AI feature triggers:** on-demand button clicks for auto-summary, anomaly explanation, and recommendations. Conserves free-tier quota and gives the user explicit control over when an LLM call fires.
- **Tab structure:** five tabs (Overview / Compare / Map / Recommendations / About) so each capability has its own real estate without crowding the headline view.
- **Live commodity prices** (`src/data/prices.py`): WTI from `/petroleum/pri/spt/` (RWTC daily) and Henry Hub from `/natural-gas/pri/fut/` (RNGWHHD monthly). Revenue Potential uses live values with as-of date in the header; falls back to constants if the live feed is unavailable.
- **U.S. choropleth map tab** (`src/ui/map_view.py`): Plotly `locationmode="USA-states"` with YlOrRd color scale.
- **Multi-region comparison tab** (`src/ui/compare_view.py`): 2–5 regions overlaid with distinct colors, side-by-side KPI table.
- **AI investment recommendation engine** (`src/ai/recommend.py`): deterministic composite score ranks regions; LLM narrates the top-N with a structured-output Pydantic schema. Aggregates and tiny-base producers are filtered out so the ranking is decision-grade.
- **Walk-forward backtester** (`src/forecast/backtest.py`): forecast accuracy measured by walking forward year-by-year and comparing predictions against actuals. Per-region MAPE displayed in the About tab.
- **At-a-glance header** (`src/ui/header.py`): 5-metric strip above the tabs always shows U.S. national context regardless of selection.
- **Chart event annotations** (`src/ui/charts.py`): faint vertical-line annotations for 2014 oil-price collapse, 2020 COVID, and 2022 OPEC+ recovery — only drawn when the event year is within the chart's x-range.

---

## Folder Structure

```
energy-intelligence-system-vivekyagnikms/
├── streamlit_app.py              # entry point; @st.cache_data + @st.cache_resource
├── requirements.txt              # pinned versions
├── LICENSE                       # MIT
├── .streamlit/
│   ├── config.toml               # dark theme + headless + cache settings
│   └── secrets.toml              # GITIGNORED; EIA + Gemini API keys
├── src/
│   ├── data/
│   │   ├── eia_client.py         # generic EIA API v2 transport (auth, retry, pagination)
│   │   ├── loader.py             # crude + gas queries + monthly→annual normalization
│   │   ├── regions.py            # canonical Region registry (national + offshore + 5 PADDs + 50 states + DC)
│   │   └── schema.py             # Pydantic ProductionRecord + ANNUAL_COLUMNS contract
│   ├── forecast/
│   │   └── engine.py             # LinearRegression with insufficient-data + horizon-cap guards
│   ├── kpis/
│   │   └── calculators.py        # required + 4 custom KPIs as pure functions
│   ├── ai/
│   │   ├── client.py             # Gemini wrapper, retry/backoff, mock toggle, circuit breaker
│   │   ├── tools.py              # 7 FunctionDeclarations + Pydantic schemas + dispatch table
│   │   ├── chat.py               # function-calling loop, system prompt, number cross-check, refusal detection
│   │   ├── summarize.py          # auto-summary with structured output + deterministic fallback
│   │   ├── anomaly.py            # statistical detection + LLM narrative explainer
│   │   └── mock.py               # canned responses for circuit-open / dev mode
│   ├── ui/
│   │   ├── sidebar.py            # region/product/year selectors → Selection
│   │   ├── kpi_cards.py          # 4 metric cards in [2,1,1,1] columns + revenue strip
│   │   ├── charts.py             # Plotly history (solid) + forecast (dashed) + 95% CI band
│   │   ├── empty_state.py        # friendly redirect for non-producing regions
│   │   ├── tools_panel.py        # Excel export · provenance popover · sensitivity slider
│   │   └── chat_panel.py         # 3 AI buttons + grounding expander + session caps
│   └── utils/
│       ├── cache.py              # parquet read/write, TTL check, seed/snapshot helpers
│       ├── excel_export.py       # openpyxl workbook builder with formula KPIs
│       └── security.py           # input sanitization + log redaction
├── data/
│   ├── seed/eia_snapshot.parquet # COMMITTED bundled fallback (1,231 rows, 2010-2026)
│   └── cache/                    # GITIGNORED; live API cache (24h TTL)
├── tests/
│   ├── test_data_loader.py       # EIA-row → DataFrame normalization
│   ├── test_forecast.py          # 9 forecast-engine tests (linear, edges, horizon, range)
│   ├── test_kpis.py              # 17 KPI tests (each KPI + combined entry point)
│   ├── test_ai_tools.py          # 12 tool-router tests
│   ├── test_ai_regression.py     # 8 mock-mode AI fallback + statistical anomaly tests
│   ├── test_security.py          # 12 input-sanitization, log-redaction, refusal-contract tests
│   ├── test_integration.py       # 3 full-pipeline tests (rows → normalize → forecast → KPIs)
│   └── test_e2e_smoke.py         # 5 import-graph tests (catches deploy-killing import errors)
├── docs/                         # this file + BRD/PRD/TDD + KPIs + case study + insights
└── planning/planning.md          # pre-build commitments
```

73 tests, all hermetic (no live EIA / Gemini calls), runs in 2.8 seconds.

---

## Data Flow

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────────────┐
│  EIA API v2  │────►│  loader.py   │────►│ canonical annual DF      │
└──────────────┘     │ • monthly→   │     │ (region_code, region_name,│
                     │   annual sum │     │  product, year, value,    │
                     │ • MBBL filter│     │  unit, n_months)          │
                     │ • cache      │     └─┬────────────────────────┘
                     └──────────────┘       │
                            ▲                ├────► forecast/engine.py (per call, microseconds)
                            │                ├────► kpis/calculators.py (pure functions)
                            │                ├────► ai/tools.py (7 tools register)
            ┌───────────────┴─────┐          │
            │  data/cache/        │          ▼
            │  data/seed/.parquet │     Streamlit UI (sidebar selection drives everything)
            │  (bundled fallback) │     ┌────────────────────────────────────────┐
            └─────────────────────┘     │ KPI cards · chart · tools row · AI panel │
                                        └────────────────────────────────────────┘
                                                      ▲
                                                      │ on-demand button click
                                        ┌─────────────┴─────────────────┐
                                        │  Gemini 2.5 Flash             │
                                        │  • function calling (7 tools) │
                                        │  • response_schema (summary,  │
                                        │    anomaly explanations)      │
                                        │  • mock fallback on 429       │
                                        └───────────────────────────────┘
```

**Two concrete data-flow examples:**

1. **User changes the year slider.** `Selection` is rebuilt. `compute_kpi_set` recomputes the four KPIs (every call inspects the same in-memory DataFrame; ~milliseconds). The chart re-renders the same history but the dotted "selected year" marker moves. No API or LLM calls.
2. **User asks the chat "Compare Texas and North Dakota crude in 2023".** `run_chat_turn` builds a contents list with the system prompt + 7 tool schemas + user message. Gemini returns a `function_call(compare_regions, regions=["Texas","North Dakota"], product="crude_oil", year=2023)`. The dispatch validates inputs against `CompareRegionsInput` (Pydantic), runs `compare_regions_impl(df, engine, args)` which queries the same DataFrame the UI is showing, and returns a typed dict. That dict is sent back to Gemini as a `function_response`; Gemini phrases the answer using only those numbers. The chat layer then regex-extracts numeric tokens from the answer and cross-checks each against the tool's returned values; matches within ±1% are "verified", others surface a `⚠ Unverified figure` warning in the grounding expander.

---

## AI Integration Design

### Core principle

**Deterministic code computes; the LLM phrases.** The LLM is never the source of truth for any number, forecast, or anomaly classification.

### Function calling, not RAG

Gemini gets seven function tools defined in `src/ai/tools.py`:

| Tool | Returns |
|---|---|
| `get_production(region, product, year)` | One value (actual or forecast), with `is_forecast` flag and unit |
| `get_history(region, product, start_year, end_year)` | Time-series of `{year, value}` |
| `compare_regions(regions[], product, year)` | Sorted-descending rows |
| `get_kpis(region, product, year)` | Full KPI bundle |
| `get_anomalies(region, product, z_threshold)` | Statistically flagged years (z-score on YoY %) |
| `list_regions(group?)` | Available regions with `has_data` flag |
| `top_producers(product, year, metric, n)` | Top-N regions by production / revenue / growth |

Each tool has a `FunctionDeclaration` (Gemini schema), a Pydantic input model (server-side validation), and a Python implementation that operates on the same `pd.DataFrame` and `ForecastEngine` the UI uses. So the AI is grounded in *the exact data the user sees on screen*.

### Structured outputs for narrative features

`auto_summary` and `anomaly_explanation` use `response_schema` with a Pydantic model. Gemini returns JSON guaranteed to match the schema; we parse with `model_validate_json`. On parse failure or 429, both features fall back to a deterministic template that uses the same grounding payload.

### Guardrail layers (13 total)

1. **Mandatory tool use** — system prompt forbids stating numbers from training knowledge.
2. **Tool input schema validation** — Pydantic rejects bad args; tool returns structured error; LLM corrects.
3. **Tool output schema validation** — Tools return typed dicts only.
4. **Number cross-check** — every numeric token in the LLM's final answer is matched against tool-returned values within ±1%; mismatches surface as "unverified" in the UI.
5. **Structured outputs** for non-chat features (`AutoSummary`, `AnomalyReport`).
6. **Detection ≠ explanation** — anomalies are flagged statistically; the LLM only narrates.
7. **No LLM forecasting** — forecasts come from `forecast/engine.py` only.
8. **Tool-call iteration cap** — 5 calls per turn, after which we return what we have.
9. **Refusal pattern** — system prompt requires a `REFUSAL:` prefix for off-topic; the UI detects it.
10. **"Show grounding" toggle** — every AI response gets an expander listing every tool call and its raw output. Any number on screen is auditable in one click.
11. **Fallback display** — if validation fails, raw tool output is shown instead of LLM prose.
12. **Rate-limit handling + circuit breaker** — exponential backoff; on persistent 429, swap session to mock-mode responses with a visible badge.
13. **Mock-mode toggle** — `MOCK_AI=true` env var bypasses Gemini for development and testing.

### Prompt engineering

System prompts are intentionally short and rule-driven:
- **Chat (~600 words):** lists the seven tools, mandates tool use, defines the refusal contract, requires unit citations.
- **Auto-summary (~250 words):** describes the JSON schema fields, gives concrete confidence-label rules (`'low' if R^2 < 0.5 or n < 8 or volatility > 1`).
- **Anomaly explanations (~200 words):** instructs to write 1-2 sentence per-year explanations citing plausible industry events; forbids inventing dates or dollar figures.

Each prompt is co-located with the feature that uses it (e.g. `SYSTEM_PROMPT` in `src/ai/chat.py`), not split across files. Prompts are versioned in git so behavior changes are auditable.

---

## Resilience

The app has three nested fallback layers so it never hard-fails during a demo:

1. **Live cache** (parquet, 24h TTL) at `data/cache/` — first port of call.
2. **Live EIA API** with retries.
3. **Bundled seed snapshot** at `data/seed/eia_snapshot.parquet` (1,231 rows, committed) — works even if EIA is down or your key has expired during judging.

For AI:
1. **Live Gemini** with retry/backoff.
2. **Circuit breaker** — after 3 failed retries, the next call short-circuits to mock mode.
3. **Mock responses** with visible badge — the dashboard continues to function when free-tier quota is exhausted.
