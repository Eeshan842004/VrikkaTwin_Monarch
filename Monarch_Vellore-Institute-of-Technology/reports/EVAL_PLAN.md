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

