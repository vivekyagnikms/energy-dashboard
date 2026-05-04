# Product Requirements Document (PRD)

**Product:** U.S. Oil & Gas Production Intelligence System
**Version:** 1.0
**Owner:** Vivek Yagnik
**Status:** Submitted

---

## 1. Product Vision

A 5-tab decision-support tool that lets a business-development analyst at an energy company evaluate any U.S. producing region in <5 minutes — with grounded AI assistance — and walk away with a defendable investment thesis.

## 2. Target Users

### Primary persona: BD Analyst "Ria"

| Trait | Detail |
|---|---|
| Role | Business-development analyst at a mid-sized E&P investor |
| Daily workflow | EIA data lookups → Excel modeling → PowerPoint for IC review |
| Tech comfort | High in Excel; moderate in Python; low in BI tools |
| Pain point | Spends 60–70% of evaluation time on data plumbing rather than analysis |
| What "great" looks like to her | Dashboard answers her IC's typical pushback questions before she asks |

### Secondary personas

- **Investment Committee member** — opens the live URL once before a meeting; expects immediate clarity, no setup.
- **Reviewer** — opens the live URL cold; expects every number to be traceable, every claim defensible.
- **Future maintainer** — picks up the codebase 6 months later; expects onboarding-grade docs.

## 3. User Stories

Numbered for traceability. Each maps to a feature in §4.

| ID | As a... | I want to... | so that... |
|---|---|---|---|
| US-1 | BD analyst | select any U.S. region | I can evaluate it without leaving the dashboard |
| US-2 | BD analyst | switch between crude oil and natural gas | I can cover both products in one tool |
| US-3 | BD analyst | sweep a year slider from past to forecast | I can see the trajectory at a glance |
| US-4 | BD analyst | see the projected production estimate updated dynamically | I can quickly answer "how big is this?" |
| US-5 | BD analyst | see growth rate, CAGR, volatility, and revenue potential alongside | I can answer "is this region worth pursuing?" |
| US-6 | BD analyst | export to Excel with editable formulas | I can extend the analysis in my normal toolchain |
| US-7 | BD analyst | stress-test forecasts against price + volume assumptions | I can stress-test before committing |
| US-8 | BD analyst | compare 2–5 regions side by side | I can rank opportunities by direct comparison |
| US-9 | BD analyst | see a U.S. map colored by production | I can scan the geographic landscape in one glance |
| US-10 | BD analyst | ask the dashboard questions in natural language | I can iterate without remembering filter syntax |
| US-11 | BD analyst | get auto-summary commentary on my selected region | I can get the "executive read" without manually constructing it |
| US-12 | BD analyst | see anomalies flagged with explanations | I can spot regime breaks I might miss |
| US-13 | BD analyst | get a ranked list of top opportunities | I can prioritize my next thesis |
| US-14 | BD analyst | trace any number back to its source | I can defend the analysis to my IC |
| US-15 | BD analyst | see how accurate the forecast model has been historically | I can calibrate trust in the forecasts |
| US-16 | IC member | open the dashboard with no login required | I can read it before the meeting in 30 seconds |
| US-17 | Judge | verify any AI claim against tool-returned data | I can trust the AI is grounded, not hallucinating |
| US-18 | BD analyst | refresh data on demand | I can ensure I have the latest EIA figures before a presentation |

## 4. Features (mapped to user stories)

Notation: **[T1]** = Tier 1 required, **[T2]** = Tier 2 differentiator, **[T3]** = Tier 3 (beyond the brief).

### F-1. Region selector — sidebar dropdown (US-1)
- Includes: 1 national + 5 PADDs + 1 Federal Offshore GoM + 50 states + DC.
- Non-producing states are kept in the list and surface a friendly empty-state UI.

### F-2. Product toggle (US-2)
- Crude oil / Natural gas radio in sidebar.

### F-3. Year selector (US-3)
- Slider from earliest data year to last full year + 5.
- Live cue: badge shows "actual" or "forecast" depending on selected year.

### F-4. Projected Production Estimate KPI (US-4)
- Past full year → actual EIA value; future / partial-year → linear-regression forecast.
- 📊 Actual / 🔮 Forecast badge per render.

### F-5. Custom KPIs (US-5)
- YoY Growth Rate, 5-year CAGR, Production Volatility, Revenue Potential.

### F-6. History + forecast chart (US-3, US-4)
- Solid history, dashed forecast, 95% confidence band, "selected year" marker.
- Industry-event annotations (2014 oil collapse, 2020 COVID, 2022 OPEC+).

### F-7. Excel export with live formulas (US-6)
- 3-sheet workbook (Historical, Forecast, KPIs).
- KPI sheet uses Excel formulas referencing the Historical sheet.

### F-8. Sensitivity controls (US-7)
- 1D slider: forecast assumption ±30% on volume, recomputes revenue.
- 2D heatmap: volume ±30% × price ±30%, RdYlGn color scale, base case outlined.

### F-9. Multi-region compare tab (US-8)
- Multiselect 2-5 regions with default = top-5 producers.
- Overlaid history + forecast chart with distinct color per region.
- Side-by-side KPI table sorted by production.

### F-10. U.S. choropleth map tab (US-9)
- Plotly state-level map colored by production.
- Top-15 producers table next to the map (includes national + PADDs + offshore that the map can't show).

### F-11. Conversational analyst (US-10)
- Chat input with 6 function-calling tools.
- "Show grounding" expander reveals every tool call, args, raw outputs.
- Number cross-check guardrail flags any unverified figure.
- Per-session caps: 30 messages, 2000 chars/input.

### F-12. Auto-summary (US-11)
- On-demand button generates narrative commentary using Gemini structured outputs.
- Confidence label (low/medium/high) is rule-driven from R², training years, volatility.

### F-13. Anomaly detection + LLM explanation (US-12)
- Statistical detection (z-score on YoY % > 2.5σ) — LLM cannot add or remove flagged years.
- Per-year narrative explanations with structured output.

### F-14. AI investment recommendation engine (US-13)
- Composite opportunity score (1.0·z(scale) + 1.5·z(5y-CAGR) − 1.0·z(vol) + 0.5·z(accel)).
- Filters out aggregates and tiny-base producers.
- Top-5 cards with Gemini-generated rationale.
- Full ranking table for transparency.

### F-15. Data provenance (US-14)
- Provenance popover (source URL, fetch timestamp, coverage stats, methodology).
- About tab shows live-vs-default badge for commodity prices.

### F-16. Live commodity prices (US-5, US-7)
- WTI from EIA `/petroleum/pri/spt/`, Henry Hub from `/natural-gas/pri/fut/`.
- Refreshed every 6h by the Streamlit cache; degrades to constants on failure.

### F-17. Walk-forward forecast backtester (US-15)
- Per-region MAPE table sorted ascending.
- Drill-down chart: actual vs walk-forward predicted for any region.

### F-18. Hosted live URL (US-16)
- Streamlit Community Cloud, free tier, GitHub-connected auto-redeploy.

### F-19. Refresh-from-EIA button (US-18)
- Sidebar button clears Streamlit cache and re-runs.

### F-20. At-a-glance header (cross-cutting)
- 5-metric strip above the tabs: U.S. crude + gas (with YoY), live WTI + Henry Hub, prices-as-of date.

## 5. Non-functional Requirements

| Category | Requirement |
|---|---|
| **Performance** | Initial load < 30 seconds (cold), < 5 seconds (warm cache). Single-region tab interactions < 1 second. |
| **Reliability** | 3-layer data resilience (cache → API → bundled seed). 3-layer AI resilience (live → backoff → mock). Demo never hard-fails. |
| **Security** | API keys gitignored locally + Streamlit Cloud secrets manager in prod. Input length cap (2000 chars). Output sanitization (no `unsafe_allow_html`). pip-audit clean of high-severity vulns. Log redaction for key-shaped tokens. |
| **Accessibility** | Color-blind-friendly palette in compare view. Tooltips on every KPI. Empty-state messages for non-producing regions. |
| **Observability** | Python `logging` at INFO; Streamlit logs visible in Cloud dashboard. AI grounding panel acts as user-facing observability for AI calls. |
| **Maintainability** | 91 hermetic tests in <4 seconds. Ruff format + lint clean. Modules <300 lines each. Module docstrings explain design choices. |
| **Cost** | Zero ongoing cost: EIA free, Gemini free tier, Streamlit Cloud free. AI free tier capped via mock fallback. |

## 6. Out of Scope (deferred)

| Idea | Reason |
|---|---|
| Authentication, multi-user | Single-tenant tool; not in problem statement |
| ARIMA / Prophet for high-volatility regions | Linear is calibrated enough (single-digit MAPE on stable regions); explainability beats accuracy at this scale |
| Real-time streaming or sub-monthly grain | EIA publishes monthly; faster grain isn't useful for BD analysis |
| Mobile-optimized layout | Desktop-first audience |
| Carbon-intensity / ESG overlay | Possible follow-on; not in this build |
| Rig-count integration as leading indicator | Possible follow-on; not in this build |
| Persistent watchlists / saved scenarios | Stateful storage out of scope |

## 7. Acceptance Criteria

The product is "done" when all of the following hold simultaneously:

- All region/product/year selectors function and update KPIs and chart in <1 second.
- Required and custom KPIs render with correct values for any supported region.
- Forecast chart visually distinguishes history from forecast and renders a confidence band.
- AI features produce grounded answers; the show-grounding panel reveals every tool call.
- Hermetic test suite passes; ruff format + lint clean.
- Live URL accessible; performance targets in §5 met.
- Documentation set complete: planning, BRD, PRD, TDD, architecture, KPI definitions, insights, case study.

## 8. Product KPIs (success metrics for the product itself)

| Metric | Target |
|---|---|
| Time-to-defendable-recommendation | <5 minutes (from URL load) |
| Number cross-check pass rate | >95% of AI responses pass the ±1% verification |
| Forecast MAPE (median across stable regions) | <10% |
| Excel-export download (proxy for real-workflow adoption) | tracked in deploy logs |
