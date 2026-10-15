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
