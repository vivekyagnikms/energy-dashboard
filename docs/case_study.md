# Case Study: Building an AI Analyst That Can't Make Up Numbers

**Project:** U.S. Oil & Gas Production Intelligence Dashboard
**Built for:** the hackathon, April 2026
**Stack:** Python · Streamlit · EIA API v2 · scikit-learn · Google Gemini 2.5 Flash · Plotly · Pydantic
**Live demo:** <https://energy-platform.streamlit.app/>

---

## The user problem

A business-development analyst at a U.S. energy investor evaluates which producing regions warrant capital and which to deprioritize. Today, that work lives in a patchwork of EIA monthly reports, state oil-and-gas-commission spreadsheets, and analyst-built Excel models, layered on top of senior-analyst tribal knowledge about which years had macro shocks and which basins are mature. Iterating across regions takes hours, not minutes, and every number ends up in a deck that has to survive an investment-committee review the same week.

The dominant constraint isn't speed — it's **defensibility**. The analyst has to be able to point at any number on her slide and say where it came from. A faster spreadsheet that produces beautiful but unverifiable forecasts makes the problem worse, not better.

I built a 5-tab Streamlit dashboard to compress that cycle to under five minutes, with grounded AI on top. The interesting design problem was making the AI useful *without* breaking the defensibility constraint.

---

## The design principle

> **Deterministic code computes; the LLM phrases.**

This sentence drove almost every architectural decision. The LLM is never the source of truth for a number, a forecast, or an anomaly classification. Computation is the job of pure Python functions — pandas filters, scikit-learn regressions, z-score statistics, openpyxl Excel formulas. The LLM's only job is to write sentences about what those functions returned.

Why this matters generally, not just here: large language models are trained to be plausible, not accurate. They will cheerfully produce a confidently-wrong number if no part of the system stops them. For analytical AI products specifically — the ones that will be put in front of investment committees, regulators, or auditors — *trust is the product*. The user's first encounter with an LLM-generated number that turns out to be wrong is also their last; they discount everything else the system says forever after. The architecture that earns that trust isn't a clever prompt; it's a structural separation between computation and prose.

That separation is what the next four sections describe.

---

## Three tradeoffs I had to defend

### 1. Linear regression over ARIMA, Prophet, and LSTM

For forecasting, the most popular modern choices are **ARIMA** (a classical statistical model that captures autoregression and moving-average effects), **Prophet** (Facebook's time-series library that decomposes trend, seasonality, and holidays), or **LSTM** (a neural network architecture for sequential data). Each is more expressive than linear regression. I picked linear anyway.

Three reasons. First, the data is too thin for any expressive model: roughly 15 annual observations per region. A two-parameter model (slope and intercept) cannot overfit that, but anything with more parameters will. Second, explainability beats accuracy at this scale: an analyst defending a forecast to her investment committee can say *"we fit a straight line through 15 years of data; here's the slope"* and survive any pushback. *"We trained an LSTM with 64 hidden units and dropout 0.2"* would not survive even one question. Third, I measured it. A **walk-forward backtest** — re-running the model as if every historical year were unknown, training through Y−1, predicting Y, comparing to actual — produced single-digit-percent **MAPE (Mean Absolute Percentage Error)** on stable regions like PADD 3 Gulf Coast, Alaska, and U.S. national. For volatile regions like North Dakota, MAPE is wider, and the 95% confidence band on the chart widens to match. Honest uncertainty quantification beats false precision from a fancier model. The MAPE table is published live in the About tab.

### 2. Function calling over RAG

For the AI integration pattern, the two main options were **function calling** (where the LLM calls predefined tools to fetch data) and **RAG (Retrieval-Augmented Generation)** (where text chunks are embedded into a vector database and the LLM retrieves the most semantically-similar chunks at query time). RAG is the popular default for "make the AI answer questions about my data."

But RAG fits unstructured text — documents, transcripts, knowledge bases. Our data is structured numbers in a table. Embedding "Texas crude oil 2022 = 1.8 million barrels" as a fuzzy semantic blob is the wrong primitive: we want exact lookups (region = TX, year = 2022), not approximate semantic matches. Math doesn't survive embedding either; *"compare Texas to North Dakota"* requires reading two specific cells and subtracting, which a retrieval system cannot do.

Function calling fits the data shape exactly. The LLM gets a list of seven tools (`get_production`, `get_history`, `compare_regions`, `get_kpis`, `get_anomalies`, `list_regions`, `top_producers`), each with a Pydantic-validated argument schema. When the user asks *"what was Texas crude in 2022?"*, the LLM returns a structured request to call `get_production(region="TX", year=2022, product="crude")`, my code runs the function against the in-memory pandas DataFrame, and the result feeds the LLM's final prose. The user sees the same number on screen and in the chat answer because the tool and the UI read from the same DataFrame.

### 3. Free-tier Gemini Flash over paid Claude Sonnet

For the LLM itself, my honest preference is Anthropic's Claude Sonnet — it has stronger tool-use reasoning. I picked Gemini 2.5 Flash anyway, because the cost-of-failure framing pointed there. A free-tier API with a generous-enough quota eliminates the highest-impact demo-day risk: *"the credits ran out during judging."* The quality gap (~80% on this workload by my estimate) gets closed by stronger guardrails, which become *more* important with a slightly weaker model, not less. With a real budget and a production deployment, I would reach for Sonnet. For a free-to-judge hackathon submission, the free path was correct.

---

## The 13-layer guardrail stack

The LLM is the riskiest component in the system, so it gets defense-in-depth. Each layer catches one category of failure; together they cover the realistic surface.

**Data integrity (Layers 1–7).** Mandatory tool use enforced in the system prompt; Pydantic input and output schema validation; **regex number cross-check** that extracts every numeric token from the LLM's prose and verifies each appears within ±1% of a tool-returned value (mismatches flagged ⚠ Unverified in the UI); structured JSON outputs for non-chat features; statistics-detect-LLM-narrates split for anomalies (z-score > 2.5σ flags the years; the LLM only writes the explanation); no LLM forecasting (forecasts come exclusively from `src/forecast/engine.py`).

**Safety (Layers 8–9).** A 5-tool-call cap per turn so the LLM cannot loop indefinitely; an enumerated refusal pattern that produces a fixed `REFUSAL:` string for any out-of-scope request, defended against prompt-injection attempts in a regression test suite.

**Audit (Layers 10–11).** A "Show grounding" expander on every AI response surfaces the tool calls, arguments, and raw outputs; a fallback display swaps the LLM prose for the raw tool table whenever cross-check or schema validation fails.

**Resilience (Layers 12–13).** Exponential backoff on HTTP 429 plus a circuit breaker that swaps to mock responses when the free-tier quota (5 requests per minute, 25 per day) is exhausted, with a visible badge so the user knows they're seeing a canned response; a `MOCK_AI=true` environment toggle for development and tests.

The single highest-leverage layer is the regex number cross-check. It mechanically catches the failure mode that everyone else's analytical-AI demos quietly fail on: the LLM correctly looks up a number via a tool, then casually adds *"up about 8% from last year"* with a number it never queried. Once you've seen this cross-check work, it's hard to ship an analytical AI product without it.

---

## What I'd do differently

Three honest cuts. **ARIMA for high-volatility regions specifically** — for North Dakota, where rig-count cycles dominate the signal, a model that captures momentum would tighten the confidence band without sacrificing explainability for the rest of the regions. **Live-API integration tests** — the existing 99-test hermetic suite uses recorded fixtures, so a schema change at EIA or Gemini would pass tests while breaking production. A small live-API smoke job in CI would catch upstream drift. **Mobile layout** — Streamlit's defaults are desktop-first; I never validated the dashboard on a phone, and the BD-analyst persona occasionally checks numbers in a meeting from her phone.

---

## What this taught me about building AI products

The temptation when integrating an LLM is to give it more agency: more tools, more autonomy, more freedom to infer. That's the wrong instinct for analytical work. The trustworthy AI product is the one where the LLM is on a tighter leash than feels comfortable — where prose is welcomed, but every number is forced through deterministic code, and every claim is auditable in two clicks.

The other lesson: trust isn't a property the user grants you once. It's a property they re-grant on every interaction, and they revoke it instantly the first time you confidently lie to them. Designing for that re-grant — surfacing tool calls, publishing your forecast accuracy, refusing rather than guessing — is the actual product work.

---

**Repo:** [GitHub](https://github.com/vivekyagnikms/energy-dashboard) · **Architecture deep-dive:** [`docs/architecture.md`](architecture.md) · **KPI definitions:** [`docs/kpi_definitions.md`](kpi_definitions.md) · **Insights surfaced by the system:** [`docs/insights.md`](insights.md)
