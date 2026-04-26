# KPI Definitions

Every KPI surfaced in the dashboard. Formulas, units, sources, edge cases. The Excel export's "KPIs" sheet replicates these as live spreadsheet formulas so a user can edit historical values and watch the KPIs recompute.

| KPI | Formula | Unit | Source code |
|---|---|---|---|
| Projected Production Estimate | actual EIA value if year ≤ last full year, else linear-regression forecast | MBBL (crude) or MMCF (gas) | `kpis/calculators.py::get_actual_or_forecast` |
| YoY Growth Rate | `(value[y] − value[y−1]) / value[y−1]` | decimal (0.10 = +10%) | `kpis/calculators.py::yoy_growth_rate` |
| 5-year CAGR | `(value[y] / value[y−5])^(1/5) − 1` | decimal | `kpis/calculators.py::five_year_cagr` |
| Volatility | `stdev(YoY%) / |mean(YoY%)|` over trailing 10 years | unitless ratio | `kpis/calculators.py::volatility` |
| Revenue Potential | crude: `value × 1000 × WTI_USD_PER_BBL`; gas: `value × MMBTU_PER_MMCF × HENRY_HUB_USD_PER_MMBTU` | USD | `kpis/calculators.py::revenue_potential_usd` |

---

## Projected Production Estimate

The headline number a BD analyst opens the dashboard for: *"how much oil/gas will this region produce in this year?"*

**Computed as:**

- **Past full years** (`n_months >= 12` for that calendar year): the actual EIA-reported value, summed from monthly observations.
- **Future years OR partial current year**: the linear-regression forecast from `src/forecast/engine.py`. The forecast is fit on full-year history only — the in-progress current year is excluded so it doesn't drag the trend toward zero late in the calendar year.

**Edge cases:**

- Region with fewer than 5 full-year observations → returns `None`. The UI shows a clean empty state suggesting top producers.
- Year more than 10 years past last observation → forecast engine raises `HorizonTooFarError`. The UI shows "insufficient data".
- Negative-going linear extrapolation → clipped at 0 (production cannot be negative).

**The `is_forecast` flag** drives UI styling: forecast values get a 🔮 Forecast badge; actuals get a 📊 Actual badge.

---

## YoY Growth Rate

Year-over-year percent change. The simplest signal of acceleration or deceleration.

`yoy = (value[y] − value[y−1]) / value[y−1]`

Returned as a decimal: 0.10 = +10%. UI formats as `±X.X%`.

**Returns `None` when:**
- Either year is missing from the data.
- The prior year value is exactly zero (would be division by zero).

**Why no smoothing:** YoY growth is intentionally raw. Smoothing belongs in the 5-yr CAGR or volatility KPIs.

---

## 5-year CAGR

Compound annual growth rate over the trailing 5 years. Smooths cyclical noise to reveal structural trend.

`CAGR = (value[y] / value[y−5])^(1/5) − 1`

**Returns `None` when:**
- Either endpoint is missing (year or year−5 not in the data).
- The start value is ≤ 0 (would produce a complex number or division by zero).

**Why 5 years:** long enough to span typical commodity cycles, short enough to react to recent regime changes (e.g. shale boom 2010-2015, COVID dip 2020).

---

## Production Volatility

Coefficient of variation of YoY % changes over the trailing 10 years.

`volatility = stdev(YoY%) / |mean(YoY%)|`

Higher = more boom/bust risk. Lower = smoother trajectory. A value of 1.0 means the standard deviation of YoY changes is the same magnitude as their average.

**Returns `None` when:**
- Fewer than 3 valid YoY observations are available (window too short).
- The mean YoY is essentially zero (denominator collapses).

**Window choice:** 10 years lets us include both boom and bust periods (e.g. 2014 oil-price collapse, 2020 COVID, 2022 OPEC+ recovery) for any region with sufficient history.

**Why coefficient of variation, not raw stdev:** a state with 2× another state's mean production would also have ~2× its raw stdev, even if relatively just as stable. Dividing by the mean makes regions comparable.

---

## Revenue Potential

Translates production volume into a dollar figure using live commodity spot prices from EIA, with deterministic fallback constants if the live feed is unavailable.

**Formulas:**

- **Crude oil:** `revenue = volume_MBBL × 1000 × WTI_USD_PER_BBL`
- **Natural gas:** `revenue = volume_MMCF × MMBTU_PER_MMCF × HENRY_HUB_USD_PER_MMBTU`
  - `MMBTU_PER_MMCF = 1030.0` (standard pipeline-quality natural-gas heat content)

**Price source:**

- **Live (preferred):** EIA spot prices —
  - WTI: `/petroleum/pri/spt/data/`, series `RWTC` (daily)
  - Henry Hub: `/natural-gas/pri/fut/data/`, series `RNGWHHD` (monthly)
- **Fallback (only if live fetch fails):** `WTI = USD 75.00/bbl`, `Henry Hub = USD 3.00/MMBtu`. The UI surfaces the as-of date and live-vs-fallback status in the at-a-glance header.

**Sensitivity controls:**
- A 1D slider stress-tests volume ±30%.
- A 2D heatmap stress-tests volume ±30% × price ±30% — color-coded red→green by revenue.

---

## Why these five KPIs?

A BD analyst evaluating regional opportunities asks five questions:

| Question | KPI |
|---|---|
| How much will this region produce? | Projected Production Estimate |
| Is it accelerating or decelerating? | YoY Growth Rate |
| Is the trend structural or noise? | 5-year CAGR |
| How risky is the trajectory? | Volatility |
| What's the dollar opportunity? | Revenue Potential |

Each KPI maps to one decision-relevant question. Adding more would clutter the dashboard without adding decision value at the BD-analyst level — leave deeper financials (capex, NPV, royalty assumptions) to specialist tools.

---

## Where to find the implementation

- All five KPIs as independent pure functions in [`src/kpis/calculators.py`](../src/kpis/calculators.py).
- `compute_kpi_set` bundles them all for one `(region, product, year)` and is what the UI calls.
- Each function is independently exposed to the AI tool router via `get_kpis` in [`src/ai/tools.py`](../src/ai/tools.py).
- Unit tests in [`tests/test_kpis.py`](../tests/test_kpis.py) cover each KPI's happy path and edge cases.
