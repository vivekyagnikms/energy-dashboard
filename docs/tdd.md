# Technical Design Document (TDD)

**System:** U.S. Oil & Gas Production Intelligence System
**Author:** Vivek Yagnik
**Status:** Implemented & deployed
**Companion docs:** [`brd.md`](brd.md) (business intent), [`prd.md`](prd.md) (product requirements), [`architecture.md`](architecture.md) (high-level architecture), [`kpi_definitions.md`](kpi_definitions.md) (KPI math)

This TDD is the engineering-side reference: data models, API contracts, control flow, deployment, security, and operational behavior. It expands on `architecture.md` with the implementation-level detail a maintainer needs.

---

## 1. System overview

A single Streamlit process running on Streamlit Community Cloud. All state is per-process (no database). External calls go to:
- EIA API v2 (production data + spot prices) — free, no SLA
- Google Gemini 2.5 Flash via `google-genai` SDK — free tier (5 RPM / 25 RPD)

Internal data flow:

```
EIA API ──► loader (normalize) ──► canonical pd.DataFrame ──► ForecastEngine ──► UI tabs
                                              │
                                              ├──► KPI calculators (pure functions)
                                              ├──► AI tool router (function calling for Gemini)
                                              ├──► Recommendation engine (composite score)
                                              └──► Walk-forward backtester
```

## 2. Data model

### 2.1 Canonical annual DataFrame (the contract)

Every component downstream of `loader.py` consumes a `pd.DataFrame` matching `src/data/schema.py::ANNUAL_COLUMNS`:

| Column | Type | Description |
|---|---|---|
| `region_code` | str | Canonical EIA `duoarea` (e.g. `NUS`, `STX`, `R30`, `R3FM`) |
| `region_name` | str | Display name (e.g. `Texas`, `PADD 3 Gulf Coast`) |
| `product` | str | `crude_oil` or `natural_gas` |
| `year` | int | Calendar year |
| `value` | float | Production volume (sum of monthly values for that year) |
| `unit` | str | `MBBL` (crude) or `MMCF` (gas) |
| `n_months` | int | Months that contributed; 12 = full year, <12 = partial |

**Why this contract:** all KPI calculators, the forecast engine, the AI tools, and the UI components read from this single shape. Changing it ripples through; we treat it as load-bearing.

### 2.2 Region registry

`src/data/regions.py` defines a `Region` dataclass and a static tuple `ALL_REGIONS` containing 1 national + 1 federal-offshore + 5 PADDs + 51 state entries. Two lookup dicts (`REGIONS_BY_CODE`, `REGIONS_BY_NAME`) are precomputed for O(1) lookups.

### 2.3 Pydantic models for AI tool I/O

`src/ai/tools.py` defines six `BaseModel` classes — one per AI tool — that validate inputs from the LLM. Each tool also has a typed output (`ToolResult` dataclass). Pydantic catches invalid arguments before they reach the implementation.

### 2.4 KPI bundle

`src/kpis/calculators.py::KPISet` is a frozen dataclass that bundles all KPIs for one (region, product, year). Includes `revenue_price_label` so the UI can disclose live-vs-illustrative prices.

## 3. External API contracts

### 3.1 EIA API v2

**Base URL:** `https://api.eia.gov/v2`

**Production endpoints used:**

| Path | Filters | Returns |
|---|---|---|
| `/petroleum/crd/crpdn/data/` | `frequency=monthly`, `facets[product][]=EPC0`, `facets[process][]=FPF` | Crude oil field production by area |
| `/natural-gas/prod/sum/data/` | `frequency=monthly`, `facets[process][]=VGM` | Natural gas marketed production by area |

**Quirk:** the crude endpoint returns *two rows per (area, period)* — one in MBBL (monthly total) and one in MBBL/D (daily average). `loader.py::_normalize_rows` filters to `units == "MBBL"` to drop the daily-average duplicate. Discovered during build via a smoke test that found summed values 1.03× too high.

**Pagination:** `length=5000` per page; `offset` increments. `EIAClient.fetch_all()` auto-paginates until a page returns < page size.

**Retry:** 3 attempts with exponential backoff (1s, 2s) on transient `RequestException`. 4xx errors (except 429) raise immediately.

**Spot-price endpoints:**

| Path | Filter | Series ID | Frequency |
|---|---|---|---|
| `/petroleum/pri/spt/data/` | `facets[series][]=RWTC` | WTI Cushing FOB | daily |
| `/natural-gas/pri/fut/data/` | `facets[series][]=RNGWHHD` | Henry Hub Spot | monthly |

(The natural-gas pricing endpoint at `/pri/sum/` returns *consumer* prices by state, not the spot price. We hit `/pri/fut/` which actually carries the Henry Hub spot series despite the URL implying futures.)

### 3.2 Gemini API (google-genai SDK)

**Model:** `gemini-2.5-flash` (free tier).

**Why not `gemini-2.0-flash`:** during build, the API key returned `quota=0` for that model — i.e. not on free tier for this account. Probed available models and locked to 2.5-flash. `MODEL_FALLBACKS` documented in `client.py` for future swaps.

**Quota:** 5 RPM, 25 RPD on free tier. Strategy: every AI feature is on-demand (button click), not auto-fire on selection change. Per-session message cap of 30.

**Function calling:** 7 tools registered (`get_production`, `get_history`, `compare_regions`, `get_kpis`, `get_anomalies`, `list_regions`, `top_producers`). Each is declared as a `genai_types.FunctionDeclaration` with explicit JSON schema.

**Structured outputs:** `auto_summary`, `anomaly_explanation`, `recommendation` features pass `response_schema` (Pydantic) + `response_mime_type="application/json"` so the model returns parseable JSON.

**Retry:** 3 attempts with exponential backoff. After 3 failures, the `GeminiClient` opens its circuit and subsequent calls short-circuit to mock responses without waiting.

## 4. Component design

### 4.1 Layered architecture

```
src/
├── data/         # Layer 1: ingestion + normalization (no business logic)
│   ├── eia_client.py  - generic transport (auth, retry, paginate)
│   ├── loader.py      - product-specific queries + normalize
│   ├── prices.py      - live commodity-price feed
│   ├── regions.py     - canonical Region registry
│   └── schema.py      - typed contract for the canonical DataFrame
├── forecast/     # Layer 2: forecasting + backtesting (pure functions)
│   ├── engine.py      - LinearRegression with guards
│   └── backtest.py    - walk-forward MAPE per region
├── kpis/         # Layer 3: KPI math (pure functions over the DataFrame)
│   └── calculators.py - 5 KPIs + KPISet bundle
├── ai/           # Layer 4: AI orchestration (function calling + structured outputs)
│   ├── client.py      - Gemini wrapper, retry, circuit breaker, mock toggle
│   ├── tools.py       - 7 tools with Pydantic input validation
│   ├── chat.py        - conversational chat loop with guardrails
│   ├── summarize.py   - auto-summary feature
│   ├── anomaly.py     - detection (statistical) + explanation (LLM)
│   ├── recommend.py   - investment-ranking engine
│   └── mock.py        - canned fallback responses
├── ui/           # Layer 5: presentation (Streamlit + Plotly)
│   ├── sidebar.py, header.py, kpi_cards.py, charts.py
│   ├── tools_panel.py (Excel + provenance + 1D sensitivity)
│   ├── sensitivity_view.py (2D heatmap)
│   ├── chat_panel.py, empty_state.py
│   ├── compare_view.py, map_view.py
│   ├── recommendations_view.py, about_view.py
└── utils/        # Layer 6: cross-cutting (cache, security, Excel)
    ├── cache.py, excel_export.py, security.py
```

**Layering rule:** higher layers can call lower layers but not the other way around. Tested implicitly by the import-graph smoke tests.

### 4.2 Streamlit caching strategy

| Cache | TTL | What |
|---|---|---|
| `@st.cache_data` for `_load_data` | 24h | Production DataFrame |
| `@st.cache_data` for `_load_prices` | 6h | Live commodity prices |
| `@st.cache_resource` for `_ai_client` | session | Gemini client instance (connection pool) |
| Underlying parquet at `data/cache/*.parquet` | 24h (mtime) | Survives across sessions |
| Bundled seed at `data/seed/eia_snapshot.parquet` | committed | Last-resort fallback |

The "Refresh data from EIA" sidebar button calls `st.cache_data.clear()` and reruns.

### 4.3 Forecast engine

`src/forecast/engine.py::ForecastEngine`. Stateless beyond the DataFrame it wraps.

**Method:** `sklearn.LinearRegression` on year → annual value.

**Guards:**
- `MIN_TRAINING_YEARS = 5` — fewer raises `InsufficientDataError`.
- `MAX_FORECAST_HORIZON_YEARS = 10` — further raises `HorizonTooFarError`.
- Partial current year (`n_months < 12`) excluded from training.
- Lower CI bound and point forecast clipped at 0 (production cannot be negative).
- Confidence band: `±1.96 × residual_std` (~95%).

**API:**
- `is_supported(region, product)` → bool (cheap; just counts full years)
- `forecast(region, product, year)` → `ForecastResult` (raises on guards)
- `forecast_range(region, product, end_year)` → DataFrame for chart drawing
- `history(region, product)` → DataFrame of full-year observations only

### 4.4 AI guardrails (13 layers)

Documented in detail in [`architecture.md`](architecture.md#guardrail-layers-13-total). Summary:

1. Mandatory tool use (system prompt)
2. Tool-input schema validation (Pydantic)
3. Tool-output schema validation (typed dataclasses)
4. Numeric cross-check (regex extract, ±1% tolerance)
5. Structured outputs (response_schema)
6. Detection ≠ explanation (anomalies are statistical, not LLM)
7. No LLM forecasting (deterministic engine only)
8. Tool-call iteration cap (5 per turn)
9. Refusal pattern (REFUSAL: prefix)
10. "Show grounding" UI panel
11. Fallback display (raw tool output if validation fails)
12. Rate-limit handling + circuit breaker
13. Mock-mode toggle

### 4.5 Recommendation scoring

`src/ai/recommend.py::rank_opportunities`. Composite z-score:

```
score = 1.0·z(scale)
      + 1.5·z(5y_CAGR)
      − 1.0·z(volatility)
      + 0.5·z(YoY − CAGR)        # acceleration
```

`z(...)` is **robust** (median / 1.4826·MAD) for resistance to long-tailed production distributions.

**Filters before scoring:**
- Aggregates (national, PADDs) excluded by default — they sum constituent states; mixing them in distorts z-scores.
- Tiny producers (`scale < 0.5% × US national`) excluded — preserves percentage-metric stability.

**LLM role:** narrate the deterministic top-N. Cannot reorder, add, or remove regions. Falls back to a deterministic per-row template on parse failure.

### 4.6 Walk-forward backtesting

`src/forecast/backtest.py::backtest_region`. Walks year-by-year:

```
for Y in valid_years (after first 5 training years):
    train_set = history[: Y - 1]
    model.fit(train_set)
    predicted = model.predict(Y)
    actual = history[Y]
    record (Y, actual, predicted, error_pct)
```

Aggregates into per-region MAPE (mean absolute percent error) and bias (mean signed % error). Skips years where actual < 1.0 to avoid MAPE blow-ups on near-zero values.

## 5. Deployment

### 5.1 Streamlit Community Cloud

- GitHub-connected; auto-redeploys on push to `main`.
- Secrets configured in the Streamlit Cloud dashboard (not committed): `EIA_API_KEY`, `GEMINI_API_KEY`, `MOCK_AI`.
- Python version pinned to **3.13** via Cloud advanced settings (we develop on 3.14 locally; Cloud caps at 3.13 currently).

### 5.2 Local dev

- `python -m venv .venv` + `pip install -r requirements.txt`.
- `.streamlit/secrets.toml` (gitignored) carries the same keys for local runs.
- `streamlit run streamlit_app.py` opens at `localhost:8501`.

### 5.3 Resilience layers

| Tier | Failure | Fallback |
|---|---|---|
| 1 | Live cache miss | Hit live EIA API |
| 2 | EIA API unreachable | Serve `data/seed/eia_snapshot.parquet` (committed, 1,231 rows) |
| 3 | Gemini live call fails | Exponential backoff (3 retries) |
| 4 | All retries exhausted | Open circuit; subsequent calls return mock responses with visible 🤖 badge |
| 5 | Streamlit Cloud cold start | Pre-warm by hitting the URL ~10 min before the demo |

## 6. Security

| Surface | Control |
|---|---|
| API keys | `.streamlit/secrets.toml` gitignored locally; Streamlit Cloud secrets manager in prod |
| User input | `sanitize_user_text()` strips control chars, caps length at 2000 |
| LLM output rendering | `st.markdown` default-safe; `unsafe_allow_html=False` everywhere |
| Logs | `sanitize_for_log()` redacts API-key-shaped tokens before logging |
| Dependencies | `pip-audit` clean of high-severity vulns at submission time |
| Transport | Streamlit Cloud terminates HTTPS |
| Prompt injection | System prompt requires REFUSAL: prefix for off-topic; circuit breaker means injection-induced 429s degrade safely to mock (never leak system prompt) |

## 7. Observability

- Python `logging` at INFO; visible in Streamlit Cloud's logs panel.
- `GeminiCallStats` (in `src/ai/client.py`) tracks request count, rate-limit hits, last error, circuit state — accessible from any caller for UI-side disclosure.
- "Show grounding" expander on AI responses serves as user-facing observability for AI calls (every tool call name, args, raw output).

## 8. Testing

| Suite | Count | Lives in |
|---|---|---|
| Data loader normalization | 8 | `tests/test_data_loader.py` |
| Forecast engine | 9 | `tests/test_forecast.py` |
| Backtester | 5 | `tests/test_backtest.py` |
| KPI calculators | 17 | `tests/test_kpis.py` |
| AI tool router | 12 | `tests/test_ai_tools.py` |
| AI regression (mock + adversarial) | 8 | `tests/test_ai_regression.py` |
| Recommendation engine | 7 | `tests/test_recommend.py` |
| Live-price label/fallback | 6 | `tests/test_prices.py` |
| Security input + log redaction | 12 | `tests/test_security.py` |
| Full-pipeline integration | 3 | `tests/test_integration.py` |
| End-to-end import smoke | 5 | `tests/test_e2e_smoke.py` |
| **Total** | **91** | runs in <4 seconds |

All tests are hermetic — no live EIA / Gemini calls in the suite. The live-fetch path is exercised manually during build, with results captured in commit messages and `docs/insights.md`.

## 9. Operational runbook (for the hypothetical future maintainer)

| Event | Action |
|---|---|
| EIA API key revoked / expired | Generate a new free key at https://www.eia.gov/opendata/register.php; update `EIA_API_KEY` in Streamlit Cloud secrets; click `Refresh data from EIA` |
| Gemini quota exhausted | App auto-degrades to mock. To reset: wait 1 minute (per-minute cap) or 24h (per-day cap). `MOCK_AI=true` env var to force mock for testing |
| EIA changes a series ID or facet | Loader will return empty rows; app falls back to bundled seed snapshot. Investigate via `python -m src.data.loader` |
| Forecast accuracy drops for a region | Check About tab → backtest table. If MAPE > 15%, the linear assumption is broken for that region; consider ARIMA or a domain-specific override |
| Streamlit Cloud deployment fails | Inspect Cloud logs; usually a missing secret or a Python-version mismatch |

## 10. Future extensions (out of scope for v1)

- ARIMA fallback for high-volatility regions (currently linear-only).
- Carbon-intensity overlay using EIA emissions data.
- Rig-count integration as leading indicator.
- Persistent watchlists (would require a real database).
- Multi-tenant auth (would require an identity provider).
- Streaming sub-monthly grain (EIA doesn't publish faster than monthly anyway).
- Proper test against a recorded VCR fixture for the EIA + Gemini live paths.
