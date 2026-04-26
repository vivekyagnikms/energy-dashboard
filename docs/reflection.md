# Build Notes

A factual record of what was built, the design choices that shaped it, and the AI tools used during development.

---

## Scope shipped

A single-page Streamlit dashboard with five tabs (Overview, Compare, Map, Recommendations, About & methodology) covering U.S. crude oil and natural gas production analysis.

**Data:**
- EIA API v2 — production data covering U.S. national, 5 PADDs, Federal Offshore Gulf of Mexico, all 50 states + DC, monthly grain, 2010 onward.
- EIA spot-price endpoints — live WTI (daily) + Henry Hub (monthly) feeding Revenue Potential.
- Three-layer resilience: live cache (24h TTL) → live API → bundled seed snapshot.

**Forecasting:**
- scikit-learn linear regression on annual full-year totals.
- ±1.96σ confidence band; partial current year excluded from training; minimum 5 training years; horizon cap of 10 years past last observation.
- Walk-forward backtester per region with public MAPE figures.

**KPIs:**
- Projected Production Estimate, YoY Growth, 5-yr CAGR, Volatility, Revenue Potential — all surfaced in the UI and computed in `src/kpis/calculators.py`.

**AI:**
- Google Gemini 2.5 Flash via `google-genai` SDK.
- Six function-calling tools operating on the same in-memory DataFrame the UI shows.
- Three on-demand AI features: conversational analyst, auto-summary, anomaly explanation.
- Investment recommendation engine with deterministic composite scoring + LLM narration.
- Number cross-check on every chat response: every numeric token in the output is verified against tool-returned values within ±1%.
- Mock-mode fallback when free-tier rate limits are hit.

**UX:**
- Tab navigation with at-a-glance header always visible.
- Industry-event annotations on the production timeline (2014 oil collapse, 2020 COVID, 2022 OPEC+ recovery).
- Excel export with KPI cells as live formulas.
- 1D sensitivity slider + 2D scenario heatmap (volume × price → revenue).
- Choropleth map of production by state.
- Color-blind-friendly palette in the multi-region compare view.

**Engineering:**
- 91 hermetic tests, runs in <4 seconds.
- Python 3.13/3.14 compatible.
- Pinned dependencies, pip-audit clean of high-severity vulns.
- Conventional Commits throughout.
- Five formal documents in `docs/`: BRD, PRD, TDD, architecture, KPI definitions, plus walkthrough script and key insights.

---

## Design choices and tradeoffs

- **Linear regression over ARIMA / Prophet.** Walk-forward MAPE is in single-digit percent for stable regions. Explainability beats marginal accuracy gains at this scale.
- **Streamlit over Next.js.** Single language end-to-end shortens the iteration cycle; GitHub-connected Streamlit Cloud deploy is one click.
- **Function calling over RAG.** The data is structured and finite; tools that query the in-memory DataFrame directly are more reliable than vector-search.
- **Deterministic scoring + LLM narration in the recommendation engine.** The LLM cannot reorder, add, or remove regions. Composite z-score does the ranking; LLM only writes the narrative.
- **On-demand AI buttons over auto-fire.** Free-tier rate limits make automatic generation on every selection change infeasible.
- **Tier 3 over depth in any one feature.** Multiple novel features (live prices, choropleth, multi-region compare, recommendation engine, walk-forward backtester) at production-quality depth, vs one feature with extreme polish.

---

## AI tools used

Claude (Anthropic) was the primary development assistant, used for:

- Initial folder structure scaffolding and `requirements.txt` generation against a moving scope.
- Writing Pydantic input schemas + Gemini function declarations together so they stayed in sync.
- Diagnosing the EIA API quirk where crude returns two rows per period (MBBL monthly total + MBBL/D daily average) — caught via a smoke-test diagnostic that would have taken longer to find by hand.
- Tests written alongside the code they cover, not as an afterthought.
- Drafting the documentation files (BRD, PRD, TDD, architecture, KPI definitions, walkthrough, insights) for human review.

The human author drove all scope, design, and verification decisions. API keys were never visible to the AI; they live in `.streamlit/secrets.toml` (gitignored locally) and Streamlit Cloud's secrets manager in production.
