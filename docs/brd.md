# Business Requirements Document (BRD)

**Project:** U.S. Oil & Gas Production Intelligence System
**Sponsor:** the hackathon
**Author:** Vivek Yagnik
**Status:** Submitted (April 2026)

---

## 1. Business Context

A U.S. energy investor invests across U.S. oil and gas opportunities. Their **business-development analysts** are responsible for evaluating which producing regions warrant capital and which to deprioritize. Today this evaluation lives in:

- A patchwork of EIA monthly reports, state oil-and-gas-commission spreadsheets, and analyst-built Excel models
- Tribal knowledge held by senior analysts (which years had macro shocks, which basins are mature vs growth)
- Slow, error-prone iteration — re-running comparisons across regions takes hours, not minutes

The firm wants to compress that cycle from "hours of spreadsheet work + senior reviews" to "minutes of dashboard interaction with grounded AI assistance" — without trading accuracy for speed.

## 2. Business Problem Statement

> **A BD analyst at a U.S. energy investor needs to evaluate U.S. oil-and-gas regional opportunities in real time, with confidence in the underlying numbers and the ability to defend recommendations to investment committees.**

Specifically, the analyst needs to answer four decision-grade questions for any region:

1. *How much will this region produce next year? In five years?*
2. *Is the trend accelerating, decelerating, or volatile?*
3. *How does it compare to peer regions on the same metrics?*
4. *Where should I focus my next investment thesis?*

A static dashboard answers (1) and (2) but misses (3) and (4). The system must close the loop with structured AI analysis, not just charts.

## 3. Business Objectives

| # | Objective | Measure of success |
|---|---|---|
| BO-1 | Compress regional evaluation cycle | <5 minutes from URL load to a defendable recommendation |
| BO-2 | Eliminate "is this number right?" friction | Every figure in the UI is traceable to source (EIA endpoint + date) |
| BO-3 | Let AI accelerate without introducing trust risk | Numerical claims in AI output are cross-checked against tool-returned values |
| BO-4 | Make outputs portable to existing analyst workflows | Excel export with KPI cells as live formulas |
| BO-5 | Cover the full U.S. opportunity surface | All 50 states + DC + 5 PADDs + Federal Offshore GoM, both crude and natural gas |
| BO-6 | Make forecast quality visible, not assumed | Walk-forward backtesting per region with public MAPE figures |

## 4. Stakeholders

| Stakeholder | Role | Primary interest |
|---|---|---|
| Business-development analyst | End user | Speed, confidence, defensibility |
| Investment committee | Consumer of analyst output | Clarity, repeatability of methodology |
| firm leadership | Sponsor | Demonstrated AI engineering judgment |
| Future maintainer | Engineering ops | Onboarding-grade documentation, hermetic tests |

## 5. Scope

### In scope
- U.S. crude oil and natural gas annual production data, 2010 → present, all states + national + PADDs + Federal Offshore GoM.
- Linear-regression forecasting with 95% confidence band, 10-year horizon cap.
- Five KPIs with formal definitions: Projected Production Estimate, YoY Growth, 5-year CAGR, Volatility, Revenue Potential.
- Live commodity prices (WTI, Henry Hub) feeding Revenue Potential.
- AI features: conversational analyst (function-calling chat), auto-summary, anomaly detection + explanation, investment recommendation engine.
- Excel export with live formulas, 2D sensitivity heatmap, walk-forward backtest viz.
- Hosted live URL on Streamlit Cloud, free-tier compatible.
- Comprehensive documentation: BRD, PRD, TDD, planning, KPI definitions, walkthrough script, reflection, key insights.

### Out of scope
- Authentication, multi-tenant, RBAC.
- Proprietary data sources (per problem statement rule).
- Production-grade observability (metrics, traces, paging).
- International data (out-of-scope per problem statement).
- Real-time streaming or sub-monthly granularity.
- Persistent user storage (watchlists, saved sessions).
- Mobile-first responsive design (desktop-first; mobile works but not optimized).

## 6. Success Criteria

The system is "successful" when a BD analyst can:

- Open the live URL and reach a defendable single-region opinion in under 5 minutes.
- Compare 2–5 regions side-by-side without leaving the dashboard.
- Get an AI-generated narrative whose numbers match the data on screen.
- Export the analysis to Excel and continue working in their familiar toolchain.
- Verify the source of any number on screen (provenance + grounding panel).
- Trust the forecasts: walk-forward backtest is visible and per-region MAPE for stable regions sits in the single-digit-percent range.

## 7. Constraints

| Constraint | Implication |
|---|---|
| Free-tier external APIs | Gemini 2.5 Flash (5 RPM cap) → on-demand AI buttons + circuit-breaker mock fallback |
| Public data sources only | EIA API v2 for production + EIA spot-price endpoints |
| Live, hosted URL | Streamlit Cloud GitHub-connected deploy; auto-redeploy on push |
| Single-language stack | Python end-to-end (data + forecasting + AI + UI); minimizes moving parts |

## 8. Risks & Mitigations (business-level)

| Risk | Mitigation |
|---|---|
| AI hallucinated numbers undermine trust | Mandatory tool calls + ±1% number cross-check + show-grounding panel |
| Live demo fails at judging | 3-layer data resilience (cache → API → seed); 3-layer AI resilience (live → backoff → mock) |
| Free-tier rate limit hit during demo | Per-session caps; on-demand AI triggers; circuit breaker |
| Forecast looks confident but is wrong | Walk-forward backtester + per-region MAPE; confidence band widens automatically with volatility |
| Numbers in dashboard differ from EIA published | Unit-handling explicitly tested (MBBL vs MBBL/D filter); sanity-checks against published US national figures during build |

## 9. Dependencies

- EIA Open Data API (free key; no SLA, but stable)
- Google AI Studio (Gemini 2.5 Flash on free tier)
- Streamlit Community Cloud (free hosting)
- GitHub (code + auto-redeploy webhook)
