# VrikkaTwin evaluation plan (pre-registered)

> Pre-registered on 14 Oct 2026, 19:43 IST, before any model was trained. This file is a verbatim copy of section 15 of the team design plan. The git commit timestamp of this file proves the metrics and pass criteria were chosen in advance. Any later change is recorded in PROGRESS.md with a reason.

**Commit `reports/EVAL_PLAN.md` (a copy of this section) to git before training any model.** The commit timestamp proves the metrics were chosen in advance.

### 15.1 Tier R: real-data component checks

| ID | Dataset | What we validate | Metric / pass criterion |
|---|---|---|---|
| R1a | MIMIC-IV demo (100 patients) + mimic-code DuckDB `kdigo_creatinine.sql` / `kdigo_stages.sql` **[V]** (creatinine itemid 50912 [V]) | Our `kdigo_stage()` reproduces mimic-code's creatinine-based stages | ≥99% agreement |
| R1b | MIMIC-IV demo + eICU-CRD demo (>2,500 unit stays, 5-min vitals, creatinine) **[S]** | Creatinine-kinetics filter: 24-h-ahead creatinine forecast | RMSE lower than last-value carry-forward and linear trend; report all three |
| R2 | UCI CKD (400 patients; Indian hospital data **[VERIFY]**) | Synthetic cohort's lab distributions | KS statistic per lab; overlay plots |
| R3 | Tawam CKD EHR (491 patients, UAE; baseline values + time to eGFR <60) **[S][VERIFY fields]** | Slow-clock **risk ranking** (not a personal-slope test; no serial eGFR) | C-index (lifelines) of `years_to_threshold(..., 60)` vs observed time to eGFR <60 |
| R4 | PMData (16 real people [VERIFY]; Fitbit HR/steps/sleep + self-reported weight) **[S]** | Real-world noise: the twin on healthy real people should **not** alarm | False red alerts per 100 patient-days on real data (target ≈0) |
| R5 | Firefighter heat dataset (21 men; capsule core temp, HR, body mass before/after) **[V]** | Exploratory: predicted vs measured body-mass loss | MAE; label "outside ISO range (PPE, >50 °C); exploratory only" |
| R6 | ISO 7933:2023 (PHS) | Heat → sweat module | Standard-based (cite); our addition is personalisation of θ |

### 15.2 Tier L: literature calibration checks

| ID | Target | Pass band |
|---|---|---|
| L1 | Triple vs no-triple AKI risk ratio in the simulated cohort | 1.2–2.0 (Lapi RR 1.31; 1.82 in the first 30 days) [V] |
| L2 | Kidney events vs temperature | ~+1% per °C (Brazil) [S] |
| L3 | Post-AKI slope penalty | −1.83 mL/min/yr (Trichy) [S] |

### 15.3 Tier S: synthetic end-to-end (headline = mismatched simulator)

Metrics, each with a 95% bootstrap CI (1,000 patient-level resamples):
- AUROC, **AUPRC**, Brier score, calibration slope and intercept;
- **sensitivity and PPV at an alert budget of 3 per 100 patient-days**;
- alerts per 100 patient-days at sensitivity 0.8;
- **median lead time** (h) from the first red alert to AKI onset, and % of events caught ≥24 h ahead;
- **within-patient AUROC** (separates a patient's dangerous days from safe ones);
- **net benefit** (decision curve) at thresholds 5–20%.

### 15.4 Robustness and fairness

- **Matched vs mismatched simulator.** The gap is reported.
- **Missingness:** 30% and 50% of wearable days dropped. **Tier 0 only:** no wearable.
- **Noise:** sensor noise ×2.
- **Forecast:** perfect forecast vs noisy forecast (§12.2). **The headline lead time uses the noisy forecast.**
- **Subgroups:** sex, age band (<60/60–74/≥75), DM vs non-DM, beta-blocker users, city, CYP2C9 phenotype, occupation.
- **Sensitivity:** tornado plot over every ASSUMPTION parameter (registry ranges).

### 15.5 Success thresholds (pre-registered targets, not promises) [A]

On the mismatched simulator:
- **M** beats B0, B1 and B2 on AUPRC and on sensitivity at the alert budget;
- median lead time ≥36 h;
- calibration slope 0.8–1.2;
- red false alerts on PMData ≈0.

If **M** does not beat **B3**, we say so and argue from robustness and the what-if capability.

### 15.6 Gate G3 (Thursday 15 Oct, 8 PM): which clock leads the pitch

- **Fast clock leads** if: R1a passes, R1b beats carry-forward, and M beats B0/B1/B2 on mismatched AUPRC with median lead time ≥24 h.
- **Otherwise the slow clock leads.** The fast clock becomes the physics risk plus rules, and the pitch emphasises the R3 C-index and kidney-years.


---

## Amendment 1 (15 Oct 2026, before any model was trained)

These changes were decided on 15 Oct 2026 after an internal review of the plan. **No model had been trained when they were made** (only the configuration, data downloads and the physiology engine existed). The original text above is unchanged; where it conflicts with this amendment, this amendment applies.

### A1.1 Cohort naming
- The training/evaluation population is called the **"enriched high-risk heat-season cohort"** everywhere. Its AKI event rate is deliberately higher than in real community populations.

### A1.2 Labels and twin risk use identical sampling
- The label and the twin's Monte-Carlo risk both use **one creatinine value per day, sampled at 08:00** (fasting morning value), the **same `kdigo_stage()` function** and the **same baseline-creatinine rule** (§9.3). Simulators may integrate hourly internally; only the daily 08:00 values feed KDIGO.
- The label means "true (simulated) AKI by daily creatinine". In real life AKI is only detected when a test is done.

### A1.3 Lead time (replaces the ≥36 h target in §15.5)
- **Primary lead-time metric:** median hours from the first red alert to AKI onset, among detected events; plus the % of events alerted ≥24 h ahead.
- Events are reported **split by trigger-to-onset gap**: trigger (fever, vomiting, diarrhoea or a new NSAID) began ≥24 h before onset vs <24 h before onset.
- **Target:** median lead time ≥24 h on the ≥24 h-gap subset. All other subsets are reported as they come out.
- The headline lead time uses the **noisy weather forecast**.

### A1.4 Gate G3 rule (replaces §15.6)
- The **fast clock always leads the pitch.** If the hybrid model M does not beat B0/B1/B2 on mismatched-simulator AUPRC, the lead becomes **B4 (twin physics risk) plus transparent rules**, with honest lead time and the what-if.
- The slow clock is a supporting panel in every case and is never the G3 fallback. G3 moves to Fri 16 Oct, 18:00 IST.

### A1.5 Prevalence-shift table (new)
- PPV, sensitivity at the alert budget, and alerts per 100 patient-days are re-computed at **1/10 and 1/50 of the synthetic event rate**, using prior-shift correction of the calibrated probabilities and PPV from sensitivity/specificity.

### A1.6 Calibration targets (L1–L3 are no longer called "validation")
- **L1:** computed **only within antihypertensive users**, triple (ACEi/ARB + diuretic + NSAID) vs double (ACEi/ARB + diuretic). Target RR ≈1.3 overall, ≈1.8 in the first 30 days of the combination. **Pass band 1.1–2.5.**
- **L2:** loose sanity check only (more kidney events on hotter days; direction and rough size), labelled as hospital-admission evidence compared with mild AKI.
- **L3:** unchanged, labelled "from a diabetic cohort (n = 274)".

### A1.7 Real-data checks: wording and scope
- **R1a:** "Labelling verified against the official mimic-code KDIGO SQL", compared with the **creatinine-only stage column** (`aki_stage_creat`). This is a correctness check, not validation of predictions.
- **R1b:** "Our creatinine equation tracks real patients". It must import the **same creatinine-kinetics function the twin uses**. Stays with dialysis/CRRT are excluded. Reported against last-value carry-forward and linear trend, whichever wins.
- **R2:** plausibility overlay of our CKD subgroup vs UCI CKD's CKD patients only. **No pass/fail KS claim.**
- **R3:** Tawam C-index reported **next to "baseline eGFR alone"** (and KFRE where valid).
- **R4 (new job):** measure real day-to-day variability of weight and resting HR in PMData and use it to inform the measurement noise parameters. "False red alerts on PMData" stays as a secondary sanity line only.
- **R5 (firefighter): dropped** (outside ISO 7933 validity: protective equipment, >50 °C).

### A1.8 New analyses
- **Heat-attributable fraction (HAF):** the same patients re-run with hourly temperature capped at 35 °C (`heat_cf_cap_c`), everything else identical. HAF = 1 − AKI episodes (counterfactual) / AKI episodes (actual). Reported overall and by subgroup: outdoor workers vs home, age ≥60 vs <60, on diuretic vs not. Reported whatever it turns out to be.
- **Heat-model sensitivity:** sweat ×0.7 and ×1.3 (AKI rate and HAF change); % of person-hours outside ISO 7933 validity per city.
- **Wearable ablation:** twin with vs without wearable signals; Tier 0 vs Tier 1.
- **Temporal held-out test:** trained on the 2024 season; the **2025 and 2026 seasons** (same synthetic patients' baselines, new weather) are held-out temporal test sets.
- **Tornado plot:** top 10 parameters only.

### A1.9 Slow clock outputs
- Shown as **ranges only** (10–90 % band). A single "kidney-years" number is never a headline. The AKI slope penalty fades over time (`aki_penalty_tau_years`) and is stage-dependent.

---

## Amendment 2 (16 Oct 2026, before any model was trained)

Decided on 16 Oct 2026 after the Part 3 report and an independent check of our claims, maths and results. **No model had been trained when this amendment was made**: the configuration, data downloads, physiology engine, personal twin and synthetic world existed; the fast-clock model, the baselines and the alert thresholds did not. Everything above is unchanged; where it conflicts with this amendment, this amendment applies. Numbers below come from `reports/*.json` at commit `8945e96`.

### A2.1 Part 3 results recorded as they came out (v1 engine, before the revision in A2.4)
- **L4 failed.** Ravi-like worker (30 M, met 3.5, 08:00-17:00 outdoors, phi_drink 0.85) on 146 real 2024 workdays with midday WBGT about 30-32 degC: **0 %** cross-shift AKI, against about 51-54 % per month in Guatemalan cane cutters (target band 20-60 %). Mean end-of-shift creatinine rise 0.003 mg/dL, maximum 0.006. One-at-a-time sensitivity (tau_recover 6 / 24 h, ECF share 0.3 / 0.7, d50 0.04 / 0.10) stayed at 0 % (maximum rise 0.020 mg/dL).
- **L5 below range.** Engine GFR fall of **12.1 / 17.5 / 19.3 %** at 3 / 5 / 8 % body-mass loss (ECF share 0.5), against 25-27 % at about 3.7 % and 27-44 % above 5 % (Belli 2018, n = 6). A healthy young kidney cannot lose more than 1 - a_tot = 20 % of GFR in this engine.
- **L1 passes as a calibration target:** pooled 2024-26 RR 2.31 (95 % CI 1.32-3.36; patient-level bootstrap percentile interval, 400 resamples), band 1.1-2.5. The truth simulator's painkiller constant was calibrated once (18 to 6 mmHg) and is not changed again.
- Event rates, heat share and demo personas: the v1 reference values are in `reports/cohort_summary.json`, `calibration_checks.json` and `demo_numbers.json` at commit `8945e96` (2024, mismatched: 6.8 AKI episodes per 100 patient-seasons; heat-attributable fraction 13.2 %).

### A2.2 Three categories for the Reality Checks page
- **Calibration (may inform parameters):** L1 (Lapi), L2 (heat sanity), sigma_hr from PMData (4.04 bpm), the SGLT2i chronic slope (EMPA-KIDNEY 1.37, 95 % CI 1.16-1.59; an input, never described as reproduced), CYP2C9 multipliers (CPIC-informed).
- **Held-out (never used for tuning):** R1a, R1b, R2 (UCI CKD only), R3 (Tawam ranking next to baseline eGFR alone), and the 2025 and 2026 test seasons.
- **Revision-informed:** L4 and L5. Their v1 failure motivated the engine revision in A2.4, so post-revision results are always shown next to the v1 failure and never as clean held-out validation.
- If any held-out check fails, it is shown as failed. Nothing is retuned silently.

### A2.3 Cohort size and test patients (replaces the N = 3,000 of Part 3)
- **2024 training season: N = 10,000 patients. 2025 and 2026 test seasons: N = 5,000 patients**, the same 5,000 in both years, drawn with a separate seed so that no test patient appears in training. This tightens A1.8, which allowed the 2024 patients to be reused.
- Targets: at least 500 AKI episodes in the training season and at least 250 per test season. If runtime does not allow it, N = 3,000 is kept, bootstrap CIs are reported everywhere, and the report says so.
- The 2024 patients are split by patient 60 / 10 / 15 / 15 into train / early stopping / isotonic calibration / internal test. The 2025 and 2026 patients are touched once, for the final report.
- Heat share is reported as a range with subgroup counts and 95 % CIs, and the office / outdoor / home pattern is explained.

### A2.4 Engine revision (pre-registered; hard stop Fri 16 Oct, 11:00 IST)
- **Why:** in v1 a 9-hour heavy shift at about 40 degC changes end-of-shift creatinine by 0.006 mg/dL, which is not credible. Two mechanisms are missing: creatinine concentrating as body water falls, and renal vasoconstriction during work and heat.
- **C1, mass-conserving haemoconcentration (must).** Creatinine mass is conserved when the distribution volume changes: Vd(t) = max((TBW - v_tot) x 10, 0.8 x TBW x 10) dL, equivalently dCr/dt = (G - GFR x Cr / 100) / Vd - Cr x (dVd/dt) / Vd. Acceptance tests: with v_tot = 0 the new engine equals the old one exactly; a 2 L water loss over 9 h at constant GFR (healthy, TBW 38.5 L, GFR 100, Cr 0.9) raises creatinine by about 2.5 %. The effect on event rates is expected to be small (a few per cent).
- **C2, exertion-related GFR fall (should).** ex_drop(t) = k_ex x clip((met(t) - 2.0) / 2.0, 0, 1), smoothed with a first-order lag tau_ex, GFR multiplied by (1 - ex_drop). Registry values: k_ex = 0.25 [A, range 0.10-0.40], tau_ex = 1.0 h [A, 0.5-3.0], met threshold 2.0 and span 2.0 [A]. No exercise-specific GFR figure was verified, so these stay assumptions, and **they are not fitted to L4 or L5**. With the registered occupation mets (delivery 2.5, construction / farm 3.0) the modelled fall is 6 % and 12.5 %; home-based people (met 1.2-1.3) are unaffected.
- **Truth simulator:** the same two mechanisms with hidden per-patient values (k_ex_true log-normal around 0.25 with sigma 0.3, clipped to 0.10-0.40; tau_ex_true uniform 0.5-2.0 h); the matched regime uses the registry values. The existing truth-only episodic exertional-muscle term (creatinine generation x1.5-2.0 on rhabdo days of heavy workers) is confirmed; no routine muscle-release term is added.
- **Expectation (not a target):** L4 improves but stays below the 20-60 % band, because a 25-30 % shift-long GFR fall gives about +0.24 to +0.29 mg/dL for Cr 0.9 and the registered mets give less. The morning value recovers (creatinine time constant about 5-9 h), which supports the 08:00 labelling rule.
- **Kill criterion:** if C2 is not implemented, tested and stable by Fri 11:00 IST, C2 is reverted (C1 is kept) and L4 / L5 are stated as a limitation: "our engine models dehydration but not exertion-related renal vasoconstriction or muscle creatinine release; it under-represents transient cross-shift creatinine rises in heavy outdoor workers."
- **Re-runs afterwards:** Part 2 tests and the scalar-vs-vector check; the G2 scenario table (old vs new); the Part 3 cohort, labels, event rates, heat share and L1; L4 / L5 on **both** the twin engine and the truth simulator; the demo personas. The hourly creatinine update is already the exact exponential within each hour (no Euler step).

### A2.5 Alert policy and operational metrics (replaces the single 3-per-100 budget in 15.3)
- **Red** (doctor review plus a home kidney test): at most **0.5 alerts per 100 patient-days**. **Amber** (patient self-care: ORS within guardrails, avoid painkillers, shade): amber and red together at most **3 per 100 patient-days**. An alert is one raised notification after hysteresis and 72-hour de-duplication, counted per 100 eligible patient-days; alert-days are reported too. Thresholds are tuned on the 2024 calibration split only.
- Reported separately for 2025 and 2026 with patient-level bootstrap 95 % CIs (1,000 resamples): **alerts per AKI caught** (number needed to alert), sensitivity at each budget, alerts per 100 patient-days, and PPV at the enriched rate and re-weighted to 1/10 and 1/50 of it (prior-shift formula on the odds). PPV can never exceed (positive-day rate) / (alert rate); that ceiling is printed next to every PPV.
- A red alert means "this patient should have a creatinine test and a painkiller review", not a diagnosis.

### A2.6 Model rules for the fast clock
- The hybrid model M is fitted on a **core set of at most 25 features** (twin posterior, Monte-Carlo risk, key drug / symptom / exposure features). The full feature set (about 55) is shown only as a sensitivity row. Events per feature (episodes and positive days) are reported.
- Monotone constraints, `min_data_in_leaf` of at least 50, early stopping on the 2024 early-stopping split.
- **All tuning, thresholds and calibration use 2024 only.** The 2025 and 2026 data are touched once, for the final report.
- Leakage tests: no simulator-hidden columns (`true_*`) or split labels in the feature table; forecast features use the noisy forecast; no feature uses data after the prediction time. Matched and mismatched results are reported side by side.
- A1.4 (the fast clock always leads; B4 plus rules is the fallback) is unchanged.

### A2.7 Reporting and wording rules
- Never display a risk of "0 %": show "<1 %" (200 Monte-Carlo draws cannot resolve less than 0.5 %) and give every risk its interval or band. Heat share is always a range ("about 5-33 % depending on assumptions") with the central value. The sweat-learning result is reported with its average under-estimate (about 15 %). Subgroup results for age >= 75 are reported, because low muscle mass can blunt creatinine rises.
- Lead-time wording: "VrikkaTwin estimates kidney-injury risk for the next 72 hours and raises the alarm as soon as risk builds: usually within hours of a sick-day trigger, and earlier when forecast heat is the driver." Severity wording: "kidney injury (usually mild, usually recovers)", never "kidney failure".
- **L3 wording corrected:** the Trichy figure is "intercurrent AKI (yes/no) associated with 1.83 mL/min/year excess eGFR loss" in one single-centre retrospective diabetic kidney disease cohort (n = 274). It is applied once for any AKI in history (fading), not per episode; a second-episode increment is an assumption capped at 2 episodes; for people without diabetes it is extrapolated.
- R2 wording: "UCI CKD dataset (origin not verifiable from the source page)". The heatstroke surveillance figure is "67,637 suspected cases and 374 deaths, 1 Mar-27 Jul 2024 (NCDC; Lok Sabha reply, Aug 2024)".
