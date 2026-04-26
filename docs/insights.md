# Key Insights Surfaced by the System

The problem statement asks: *"Key insights surfaced by your system."* These are the seven decision-grade observations a BD analyst would walk away with after one session on the dashboard.

> All numbers below are reproducible — they are produced by the live system from public EIA data, not asserted from training knowledge. Every figure links to the part of the dashboard that surfaces it.

---

## 1. The Permian Basin (Texas + New Mexico) is the most attractive U.S. opportunity envelope for crude

- **Texas** ranks #1 on the composite opportunity score (Recommendations tab) for crude. Most recent annual production: **2.1B bbl**. 5-year CAGR: **+3.4%**. Volatility: **1.33** (CV of YoY %).
- **New Mexico** ranks #2. Smaller scale (**0.82B bbl**) but the strongest growth in the U.S. crude top-5: **+16.7% 5-year CAGR**, low volatility (**0.56**).
- Combined, these two states represent **~40% of US national crude** and account for the entire net-positive growth — most other major producers have flat or negative CAGRs.
- **BD implication:** acreage in the Permian fairway (Midland or Delaware sub-basin) remains the highest-confidence growth play. New Mexico in particular has the better scale-adjusted growth — most BD teams are already heavy in Texas.

## 2. North Dakota crude has decoupled from oil-price recovery

- 5-year CAGR: **−0.6%** (declining). Volatility: **6.27** (highest among major producers).
- Walk-forward backtest MAPE for ND crude is roughly **15–20%** (About tab) — much higher than the **<10%** typical for stable basins. The linear forecast cannot capture ND's structural breaks (shale boom 2010–2014 → bust 2015 → recovery → COVID → flat).
- **BD implication:** Bakken is now a maintenance basin, not a growth basin. Capital allocated to ND should be benchmarked against Permian on per-well economics, not on CAGR projections.

## 3. The Marcellus / Utica corridor dominates U.S. natural gas growth

- **Pennsylvania** ranks #3 on the gas opportunity score. Production **7.7M MMCF/year** (~7.7 Tcf), volatility **1.21**, CAGR +1.4%.
- **West Virginia** ranks #4 with stronger growth (+7.0% CAGR) and lower volatility (0.45).
- Together they produce **~28% of US natural gas** and the highest scale-adjusted growth nationally is in WV.
- **BD implication:** the Appalachian dry-gas window (predominantly Utica in WV, Marcellus in PA) is structurally outperforming Texas Eagle Ford and Haynesville on both growth and stability.

## 4. Federal Offshore Gulf of Mexico is fragile

- Crude scale: **0.69B bbl/year**. CAGR: **+2.6%**.
- Volatility: **3.08** — third-highest of any producing region for crude.
- Walk-forward backtest MAPE: **~8.1%** with a small **−2.6% bias** (forecasts tend low).
- **BD implication:** GoM offshore is a high-output, high-risk region — single-event shocks (hurricanes, refinery outages, deepwater incidents) drive most of the variance. Position sizing should reflect this; the recommendation engine penalises it accordingly (rank #4 despite large scale).

## 5. Production volatility predicts forecast accuracy

- Walk-forward backtest (About tab) shows a clear correlation between a region's volatility KPI and its MAPE: **PADD 5 West Coast** (volatility 0.4) has **1.9% MAPE**; **North Dakota** (volatility 6.3) has **>15% MAPE**.
- Linear regression assumes smooth trends — it is well-calibrated where production is smooth and miscalibrated where it isn't.
- **BD implication:** trust the forecast for low-volatility regions; demand human review for forecasts in regions with volatility > 2.0. The dashboard's confidence band (±1.96σ residual) widens automatically in noisy regions, but BD analysts should treat any single point estimate there as indicative, not committable.

## 6. Live commodity prices materially change Revenue Potential conclusions

- Live WTI is currently **~21% above** the illustrative $75/bbl constant we shipped with. For US national 2025, this moves Revenue Potential from **USD 371.9B (illustrative)** to **USD 451.6B (live)** — an USD 80B/year delta on the same volume.
- The 2D scenario heatmap (Overview tab) shows revenue under all combinations of volume ±30% × price ±30%; the spread can be **2.5×** between worst and best corners.
- **BD implication:** any investment thesis that assumed a $75/bbl long-run price is currently understating revenue by ~20% at base case. Run the heatmap before stakeholder presentations.

## 7. AI-flagged anomalies cluster around three macro events

- Across the 12 highest-volatility crude regions, statistically flagged anomalies (z-score on YoY % > 2.5σ; About → Anomalies tab via the Conversational analyst) cluster in **2014–2015** (OPEC oversupply / oil price collapse), **2020** (COVID demand shock), and **2022** (post-COVID recovery + OPEC+ cuts).
- Almost no anomalies cluster in years without macro events — confirming the dashboard's z-score detector is not over-flagging noise.
- **BD implication:** the dashboard's anomaly flags are macro-aware by construction, not basin-specific. A flag in any year not in the macro list above warrants extra investigation — it likely reflects regulatory, infrastructure, or operator-specific disruption rather than market context.

---

## How to verify any of these

Every insight above is backed by something visible in the live app:

- **#1, #2, #3:** Recommendations tab → top-5 cards + full ranking table.
- **#4:** About tab → MAPE table, drill-down chart for Federal Offshore GoM.
- **#5:** About tab → MAPE table, sorted ascending. Compare against the volatility column on the Recommendations full ranking.
- **#6:** At-a-glance header strip (live WTI/HH) + Overview tab → 2D scenario heatmap in the Tools row expander.
- **#7:** Overview tab → AI panel → "🚨 Detect anomalies" button; or chat the analyst with *"What anomalies are in North Dakota crude?"*.
