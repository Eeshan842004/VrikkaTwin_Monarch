# VrikkaTwin build log

Team Monarch, Vellore Institute of Technology. The build follows the team's design plan in 8 parts, with a stop after each part. Every entry records what was built, the test results, key numbers (with their source file), decisions, deviations from the plan, open issues and commit hashes.

| Part | Phases | Gate | Status |
|---|---|---|---|
| 1 Foundation | P0 + P1 | G0, G1 | **done** (G0 `ef100fe`, G1 see below) |
| 2 Physiology engine | P2 | G2 | **done** (G2, see below) |
| 3 Twin + synthetic world | P3 ‖ P4 | exit checks | **done** (see below) |
| 4 Fast clock | P5 | G3 | **done** (G3, see below) |
| 5 Slow clock + what-if | P6 + P7 | exit checks | **done** (see below) |
| 6 Backend + trust layer | P8 | G4 | **done** (see below) |
| 7 Frontend + evaluation | P9 ‖ P10 | G5 freeze | not started |
| 8 Deliverables + submission | P11 | G6 | not started |

---

## Decisions v1 (15 Oct 2026, 21:30 IST)

The team reviewed the plan before training any model and recorded 20 decisions (private decision log). Metric changes are in `reports/EVAL_PLAN.md`, "Amendment 1" (own commit `48e1546`).

**Applied on 15 Oct (before Part 2):**
- **Framing:** a kidney twin for heatwaves **and sick days**; "sick-day rules" renamed "sick-day guidance" in all plan files.
- **Registry (`config/parameters.yaml`):**
  - `sglt2_loss_l_day` set to 0 (range 0–0.15, sensitivity only);
  - new `half_life_mra_h` 24 h;
  - new `heat_cf_cap_c` 35 °C, `sweat_cap_l_h` 1.5, `sweat_sensitivity_low/high` 0.7/1.3, `creatinine_sample_hour` 8;
  - new `aki_penalty_tau_years` 2 and stage multipliers 0.5/1.0/1.5, plus `sglt2i_initial_dip` 3;
  - CPIC 2020 wording on the CYP2C9 multipliers.
- **Drug lexicon:**
  - CPIC classes (lornoxicam and tenoxicam genotype-adjusted; naproxen and indomethacin not);
  - `half_life_key` for every drug class that changes the kidney model;
  - sick-day pause reasons (SGLT2i = ketoacidosis risk, metformin = lactic acidosis risk).
- **Languages:** EN, HI, KN, TE only. City defaults are Nagpur → hi and Chennai → en.
- **Weather:** 2025 and 2026 seasons downloaded as held-out test seasons. Files moved to `data/weather/<year>/`. Both later seasons were milder than 2024 (Delhi peak 43.7 °C and 44.4 °C vs 46.0 °C).
- Plan files (master plan, `BUILD_PARTS.md`, `BUILD_PLAN_DETAILED.md`) carry a "Decisions v1" banner that overrides conflicting text, and the new schedule.

**Not applied: conflict found with the data (item 12, `sigma_hr`), waiting for a team decision.**
- PMData **weight** is self-reported and mostly whole kilograms: 11 of 15 people report integers ≥85 % of the time, with 3–6 distinct values in ~3 months. Its day-to-day SD (median 0.36 kg) is rounding, not scale noise. As item 12 allows, `sigma_weight_kg` stays at 0.4 with its range.
- PMData **resting HR** day-to-day SD has a median of 1.24 bpm (14 people). But Fitbit's resting HR is an algorithmically smoothed daily value, so it understates real measurement noise. Setting `sigma_hr_bpm` from it (4 → ~1.2, or ~0.9 after dividing by √2) would make the twin over-trust heart rate and inflate the apparent value of wearables. `sigma_hr_bpm` stays at 4.0 until the team decides. It is not used until Part 3.


_Started Wed 14 Oct 2026, 19:30 IST._

### Decisions and deviations
- **Python 3.12, not 3.11.** `shap==0.53.0` (a pinned §17 version) requires Python ≥3.12. The plan lists 3.12 as acceptable, so the venv uses CPython 3.12.14. All other §17 pins resolved at their exact versions.
- **Team folder name** `Monarch_Vellore-Institute-of-Technology` (hyphens instead of spaces so paths and URLs stay safe).
- **CI workflow at the repo root** (`.github/workflows/ci.yml`, `working-directory` = team folder), because GitHub only runs workflows from the repository root.
- **`tasks.py` mirrors the Makefile**, because `make` is not installed on the Windows build machine.
- **Drug effect half-lives are per drug** in the registry (HCTZ 12 h, chlorthalidone 48 h, indapamide 24 h [new ASSUMPTION], loop 6 h), replacing the single hard-coded 48 h diuretic value in the plan's twin snippet.
- **New registry ASSUMPTIONS not in the plan's table** (each with a range): `half_life_indapamide_h`, `sigma_sbp_mmhg`, `indoor_offset_thatch_c`, `indoor_offset_cooler_c`.
- **Fever is always "°C above 37"** everywhere in the registry and code.
- **PhysioNet demos downloaded table by table.** PhysioNet throttled each connection to ~5–7 KB/s, so the full zips (16 MB / 137 MB) would have taken hours. `download_public_data.py` fetches only the tables we use, as parallel byte-range chunks.
- **UCI CKD from the CSV endpoint.** The zip wraps a `.rar`; UCI serves the same 400-row table as `data.csv`.
- **PMData as a per-participant subset** (resting HR, sleep score, activity minutes, self-reported weight and fluid glasses, wellness) via the OSF API. The full zip is 1.4 GB.

### Gate G0 (P0): passed, commit `ef100fe`
- `reports/EVAL_PLAN.md` (verbatim plan §15) committed before any model code.
- `tests/test_config.py`: 8/8 pass. Every §8 parameter is registered, every ASSUMPTION has a range, and all YAML files are well-formed.

### Environment (reports/env_check.json)
- 28/28 libraries import on Python 3.12.14. Key versions: numpy 2.2.6, scipy 1.18.1, pandas 3.0.6, pythermalcomfort 4.6.1, filterpy 1.4.5, lightgbm 4.7.0, scikit-learn 1.9.1, shap 0.53.0, kfre 0.1.18, streamlit 1.65.0, faster-whisper 1.2.1, cryptography 50.0.2, PyJWT 2.15.1, rapidfuzz 3.14.6.
- 6/6 micro-checks pass:
  - PHS sweat at 40 °C / 40 % RH / met 2.5 = **0.608 L/h** (plan 0.61);
  - **filterpy UKF works on numpy 2.2**, so no in-house UKF is needed;
  - native `lgb.train` + `pred_contrib`;
  - KFRE golden **0.0305 / 0.1132**;
  - `st.audio_input` present;
  - faster-whisper imports.
- Registry: `config/parameters.yaml` holds every constant with provenance (CITED / VERIFY / ASSUMPTION).

### Gate G1 (P1): passed
**Weather** (`data/weather/*.parquet`, Open-Meteo ERA5, CC BY 4.0; 2,928 hourly rows per city, 0 missing):

| City | Peak (°C) | Date | Days ≥ 40 °C |
|---|---|---|---|
| Delhi | 46.0 | 26 May 2024 | 42 |
| Nagpur | 45.5 | 27 May 2024 | 44 |
| Ahmedabad | 46.5 | 23 May 2024 | 69 |
| Hyderabad | 41.4 | 4 May 2024 | 7 |
| Palasa (Uddanam) | 42.5 | 25 Apr 2024 | 13 |
| Chennai | 41.0 | 28 May 2024 | 4 |
| Bengaluru (control) | 39.5 | 1 May 2024 | 0 |

**Datasets** (`data/raw/`, gitignored; `reports/data_inventory.json`):

| Dataset | Check | Status | Notes |
|---|---|---|---|
| MIMIC-IV demo v2.2 | R1a, R1b | ok, 8 tables | 100 patients, 140 ICU stays, 3,003 creatinine values |
| eICU-CRD demo v2.0.1 | R1b | ok, 2 tables | 2,520 stays, 14,603 creatinine values |
| UCI CKD | R2 | ok | 400 rows; one dirty label `ckd\t` to clean in Part 3 |
| Tawam (PLoS ONE S2) | R3 | ok | 491 patients; **baseline eGFR + `TimeToEventMonths` + `EventCKD35`** (no serial eGFR, as §15.1 assumed); creatinine in µmol/L |
| PMData | R4 | ok, 125 files | **16 participants confirmed**; daily resting HR, self-reported weight **and fluid glasses** |
| Firefighter heat | R5 | ok | one workbook, 12 sheets, including body mass / hydration |

**mimic-code KDIGO** (official DuckDB SQL, MIT, vendored in `scripts/sql/mimic_code/`) built `data/raw/validation.duckdb` in 5 s:
- kdigo_creatinine 1,272 rows; kdigo_stages 8,729 rows;
- creatinine stages 0/1/2/3 = 990 / 155 / 65 / 62.

**Tests:** 17/17 pass (8 config + 9 data); ruff clean.

### Open items for later parts
- UCI CKD label cleaning (Part 3, R2).
- Tawam creatinine is µmol/L, so it goes through the unit converter (Part 5, R3).
- §10.1 snippet fixes (per-drug half-lives, fever above 37 °C, daily KDIGO grid, §9.3 baseline) are applied in Parts 2–3.

---

## Part 2: Physiology engine (P2)

_Built Thu 15 Oct 2026 night, after Decisions v1._

### Files
- `src/vrikka/physiology/equations.py`: CKD-EPI 2021 (+ its inverse), KFRE 4-variable, KDIGO staging, the shared **08:00 daily-sampling helper** (`daily_samples`, `kdigo_daily_stages`), creatinine/UACR unit handling, and the §9.3 baseline rule.
- `src/vrikka/physiology/heat.py`: ISO 7933 PHS lookup table (met units, `limit_inputs=False` + validity mask, sweat cap, cached per body-size band), radiant offset, indoor temperature, wet bulb, heat index.
- `src/vrikka/physiology/renal.py`: registry-driven `Params.from_patient`, two-deficit volume model, **per-drug** lagged effects, autoregulation, and `creatinine_step`, the single creatinine-kinetics function that R1b and the twin will import.
- `src/vrikka/physiology/batch.py`: the vectorised engine (same equations, arrays of patients or draws).
- `src/vrikka/physiology/pk_nsaid.py`: tablets → genotype-adjusted NSAID units (CPIC 2020 classes), paracetamol tally.
- `src/vrikka/physiology/potassium.py`: stub only.
- `scripts/physiology_scenarios.py` → `reports/physiology_scenarios.json`.

### Gate G2: passed
- Tests: **61/61 pass** (`test_equations` 10, `test_heat` 6, `test_renal` 14, plus config/data). Ruff clean.
- Golden values: CKD-EPI 64.5 / 73.7; KFRE 0.0305 / 0.1132, matching the `kfre` package to 1e-6.
- The vectorised engine matches the scalar engine to 1e-4 over 12 random patients × 5 days.
- A test fails if any kidney drug lacks a registered half-life or if a hard-coded half-life table appears in the source.
- **Scenario ordering holds** (none < NSAID < ARB+diuretic < triple < triple+fever) in both runs.
- Benchmark: 33,000 trajectories × 2,928 hourly steps in **13.0 s** (plan estimate ~6 s; fine).

### Scenario table (`reports/physiology_scenarios.json`)
Kamala-like patient (68 F, 62 kg, eGFR 58, a_tot 0.693, phi_drink 0.60). Real Nagpur weather 26–28 May 2024 (peak 45.5 °C, RH 29.5 %). 9 h outdoors. KDIGO uses daily 08:00 creatinine.

| Scenario | Water deficit (L) | ECF deficit (L) | Peak ΔCr (hourly) | ΔCr at 08:00 | Min GFR | KDIGO | Same with air capped at 35 °C |
|---|---|---|---|---|---|---|---|
| No drugs | 1.69 | 0.85 | +0.146 | +0.098 | 83.5 % | 0 | +0.056, 0 |
| NSAID only | 1.69 | 0.85 | +0.247 | +0.160 | 74.2 % | 0 | +0.091, 0 |
| ARB + diuretic | 1.79 | 0.95 | +0.395 | +0.288 | 63.9 % | 0 | +0.169, 0 |
| Triple whammy | 1.79 | 0.95 | +0.578 | +0.412 | 53.1 % | **1** | +0.237, 0 |
| ARB + diuretic + fever | 1.94 | 1.02 | +0.466 | +0.349 | 60.9 % | **1** | +0.230, 0 |
| Triple + fever | 1.94 | 1.02 | +0.693 | +0.508 | 49.3 % | **1** | +0.325, 0 |
| Triple + fever, CYP2C9 *3/*3 | 1.94 | 1.02 | +0.810 | +0.597 | 44.3 % | **1** | +0.369, 0 |

### Surprises (for the team)
1. **With phi_drink 0.60, three scenarios reach KDIGO stage 1, not one.** The plan's §9.1 prototype used phi_drink 0.75; with 0.75 the ordering is the same and only triple + fever crosses +0.3 on the hourly peak (+0.303), while no scenario crosses at 08:00. `phi_drink` is the most influential setting seen so far.
2. **Daily 08:00 sampling reads about 30 % lower than the hourly peak** (creatinine peaks around midnight after the hot day and recovers overnight).
3. **Engine-level heat contribution is large for this exposure.** Capping air temperature at 35 °C removes every AKI and cuts the creatinine rise by about half (e.g. triple + fever +0.693 → +0.325). This is a worst case: a 68-year-old 9 h outdoors in 45.5 °C sun.
4. **ISO validity:** 0 % of outdoor hours outside ISO 7933 in dry Nagpur heat. The validity problem is in humid heat (Chennai, Palasa) and will show in Part 3.
5. **The sweat cap never binds** for this body size (maximum on the whole grid 1.02 L/h < 1.5).
6. A chronic chlorthalidone + ARB patient settles at creatinine about 2 % above `cr_base` (1.048 → 1.069) before any heat: the plan's "steady ECF offset", now visible.

### Deviations from the plan
- `creatinine_step` uses the **exact** solution of the kinetics ODE over each step instead of the plan's Euler step (same equation; stable for the long gaps between labs in R1b).
- The CYP2C9 multiplier is applied to the NSAID dose for CPIC-covered drugs only, not inside `gfr_now` as in the plan's snippet, so a patient on diclofenac gets no genotype effect even if they are a poor metaboliser.

---

## Decisions v2 (15 Oct 2026, ~23:00 IST): G2 answers + dataset findings

- **sigma_hr (A-5a): applied.** Our own nightly resting HR from PMData's **raw** Fitbit stream (lowest 30-min rolling mean 00:00–06:00, nights with ≥4 h of data); per-person SD vs rolling 7-day median; median over the **15 of 16** people with ≥30 nights = **4.04 bpm** (person range 1.7–6.3). This is above the 3 bpm floor. `sigma_hr_bpm` = 4.04, CITED (`reports/pmdata_noise.json`). Beta-blocker users get ×1.5 (`sigma_hr_beta_blocker_mult`).
- **phi_drink (A-5b): applied.** Means kept (0.60 for age ≥60, 0.75 otherwise, ×0.8 without water at work). Per-patient Beta draws with SD 0.10 (`phi_drink_sd`), clipped 0.30–0.95. Marked a top-3 tornado parameter. Twin test added (low vs high drinker separates).
- **ORS split (B2): applied.** Plain water refills the ECF in proportion to v_ecf/v_tot; ORS refills 0.9 of its volume (`ors_ecf_frac`).
- **L4 and L5 (B1, B4): run** (results below). **OSF dm3qf (B1d): NOT AVAILABLE.** It holds 194 paired serum/point-of-care creatinine values but declares no licence; inspected for structure only.
- **BD-KDD (B3): NOT USED (conflict with the data).** The values look synthetic:
  - 92.7 % of the "healthy" class have creatinine > 1.5 mg/dL (median 7.1);
  - creatinine vs urea r = 0.005 (UCI 0.59), creatinine vs class r = 0.03;
  - most columns are indistinguishable from flat uniform distributions.

  The source permission letter also restricts use to one approved academic purpose. A download script is kept; details are in `docs/DATA_SEARCH.md`.
- **UCI CKD origin:** the UCI page names no hospital, city or country, so no site is stated anywhere.
- **docs/DATA_SEARCH.md (D): written.** Covers sources searched, what we use, what was assessed and rejected, the calibration targets, why the label uses morning creatinine, and what does not exist openly.
- C-list items (bovine data, synthetic Kaggle data, NephTox, Boston Marathon paper, Leete & Layton code, "make L1 identical"): not used, as decided.

---

## Part 3: Personal twin + synthetic world (P3 ‖ P4)

### Built
- **Twin:** `twin/ukf_twin.py` (5-state UKF; the daily 08:00 → 08:00 predict runs all 11 sigma points through the vectorised engine; weight, HR and SBP updates with missing channels via `missing_channel_r`; lab update; `cr_daily` history), `twin/measurement.py`, `twin/risk_mc.py` (Monte-Carlo 72-h risk with the **same** `kdigo_daily_matrix` + `aki_onsets` as the labels), `twin/replay.py` (persona replays for demos and the Time Machine).
- **Neutral exposure:** `physiology/exposure.py` (weather + routine → hourly sweat for many people, BSA-scaled from one reference PHS table per sex; noisy forecasts; weather reader). Shared daily KDIGO functions in `physiology/equations.py`.
- **Simulator:**
  - `simulator/cohort.py` (hidden `true_*` columns);
  - `events.py`, `ground_truth.py` (mismatched pressure-autoregulation model + matched engine regime);
  - `labs.py`, `devices.py` (HealthKit / Google Fit / FHIR export shapes);
  - `weather.py`, `world.py`.
- **Labels:** `fastclock/labels.py` (onset within 72 h on daily 08:00 values, exclusions, 7-day episode rule).
- **Scripts:** `generate_cohort.py`, `calibration_checks.py`, `l1_pooled.py`, `validate_l4_l5.py`, `validate_r2.py`, `pmdata_noise.py`, `make_demo_patients.py`.
- **Config:** `config/scenarios.yaml` (S1–S6, fictional personas); Part 3 routine assumptions appended to `config/cohort.yaml`.
- **Tests:** `test_twin.py` (8), `test_simulator.py` (9), `test_scenarios.py` (6). **85/85 pass** (56 in CI). Ruff clean.

### Key numbers (enriched high-risk heat-season cohort, 3,000 patients; `reports/cohort_summary.json`)
| Season | Regime | AKI episodes | Per 100 patient-seasons | Patients with ≥1 AKI | AKI patient-days | Label-positive eligible days |
|---|---|---|---|---|---|---|
| 2024 (train) | mismatched (headline) | 205 | 6.8 | 5.5 % | 0.50 % | 0.15 % |
| 2024 | matched | 443 | 14.8 | 10.5 % | 0.56 % | 0.35 % |
| 2025 (test) | mismatched | 160 | 5.3 | 4.2 % | 0.44 % | 0.12 % |
| 2026 (test) | mismatched | 208 | 6.9 | 5.0 % | 0.48 % | 0.16 % |

Episodes use a 7-day gap rule (raw onsets 2024 mismatched = 266). Almost all onsets are KDIGO stage 1 (265 of 266).

**Heat-attributable fraction** (2024, mismatched, 35 °C cap; `reports/calibration_checks.json`):
- overall **13.2 %**;
- outdoor workers 15.0 %, home-based 7.0 %, office 14.3 %;
- age ≥60 16.9 % vs <60 8.0 %;
- on diuretic 16.1 % vs not 12.1 %;
- matched regime 32.7 %.

Sweat sensitivity: ×0.7 → 5.2 per 100 patient-seasons, HAF 5.1 %; ×1.3 → 9.1 per 100, HAF 15.4 %. Person-hours outside ISO 7933 validity: 0–2.6 % by city (outdoor hours ≤0.7 %).

**Calibration targets:**
- **L1 (`reports/l1_pooled.json`): pooled 2024–26 RR 2.31 (95 % CI 1.32–3.36), PASS** (band 1.1–2.5). Per season: 2.73 (1.00–4.96), 2.31 (0.87–4.17), 1.87 (0.81–3.44). Only 15–23 triple-therapy events per season, so single seasons are noisy.
  - The truth model's NSAID constant was calibrated once to this band. 18 mmHg gave RR 4.46 in a trial run; 6 mmHg was chosen (trial RR 1.76) and not changed afterwards.
- **L2:** +0.06 % per °C. Direction correct; much smaller than the Brazil admissions figure (+0.9 %).
- **L4 (`reports/literature_checks_l4_l5.json`): far outside the 20–60 % band.**
  - Ravi-like worker (30 M, met 3.5, 08:00–17:00 outdoors, phi 0.85) on 146 real 2024 workdays with approximate midday WBGT 30–32 °C: **0 %** cross-shift AKI. Mean end-of-shift rise 0.003 mg/dL (max 0.006); next morning 0 %.
  - Sensitivity (tau 6/24 h, ECF share 0.3/0.7, d50 0.04/0.10): still 0 %, max rise 0.02 mg/dL.
- **L5:** engine GFR fall at 3 / 5 / 8 % body-mass loss = 12.1 / 17.5 / 19.3 % (ECF share 0.5; range 5.0–19.8 %) vs Belli 25–27 % at ~3.7 % and 27–44 % above 5 %.
  - **Structural ceiling:** a healthy young kidney (a_tot 0.8) can lose at most 20 % of GFR in our model. Not tuned, as decided.

**R2 (`reports/r2_overlay.json`, `reports/figures/r2_overlay.png`):** non-CKD creatinine median 0.92 vs UCI 0.90. Our CKD subgroup is milder (1.54 vs 2.20 mg/dL) because it is G3 only. Haemoglobin in non-CKD is lower than UCI (12.95 vs 15.0).

**Twin (`tests/test_twin.py`):**
- Sweat multiplier true 1.4, hot outdoor week + one lab: mean over 10 seeds **1.19** (15 % off; within the 20 % target on average), 8/10 individual seeds within 20 % (6/10 at the milder 0.55 L/h peak).
- Low vs high drinker (phi 0.45 vs 0.75): learned theta separates in the right direction in all seeds (~1.17 vs ~0.80).

**Demo personas (`reports/demo_numbers.json`; fictional; provisional thresholds 5 % / 15 %):**
- **S1 Kamala (home-based):** green → amber (9 %, 6 %) → **red 45 % the day before her simulated stage-1 AKI** (lead 23 h; the fever starts that day). What-if: continue 41 % → painkiller swap 25 % → + ORS 0 % → + pauses 0 %; CYP2C9 *3/*3 51 %; no illness 0.5 %.
- **S2 Ravi:** green all 12 days.
- **S3 Fatima:** red the day vomiting starts, AKI next morning.
- **S4 Mr Iyer:** green, max 2.5 %.
- **S5 hydrated:** green all 12 days while the heat-index rule fires on all 12.
- **S6:** poor metaboliser max 10.5 % vs normal 8.5 %.

### Deviations and choices to note
1. **Mismatched truth NSAID constant calibrated** to L1 once (18 → 6 mmHg), recorded above.
2. **Episode counting** uses a 7-day gap rule (the same window labels exclude), because patients near the threshold flicker in and out of stage 1.
3. **Body size** in the heat model: one reference PHS table per sex, scaled by body surface area (approximation; avoids dozens of tables).
4. **Twin learning target:** the 20 % / 7-day criterion is met on the mean of 10 seeds, not for every individual (8/10). Reported, not loosened.
5. **The cohort's CKD G3 share (15 %, from `cohort.yaml`)** is higher than the ICMR figure of 8 % in DM+HTN: the cohort is enriched by design.
6. **Weather reader moved** to the neutral `physiology/exposure.py`, because the import-lint test caught the twin importing the simulator package.


## Decisions v4 / v5 (16 Oct 2026, 00:15-01:00 IST) and the steps before Part 4

v5 wins wherever it conflicts with v4. Every number below is from the named report file.

### Amendment 2 (commit `09a8617`, before any model was trained)
`reports/EVAL_PLAN.md` now records:
- the v1 L4 / L5 misses;
- the calibration / held-out / revision-informed categories;
- the cohort size;
- the pre-registered engine revision with its 11:00 kill time;
- the red <= 0.5 / amber + red <= 3 alert budgets, with alerts per AKI caught and the PPV ceiling;
- the <= 25 core-feature rule, 2024-only tuning and the leakage tests;
- the wording rules.

### Engine revision (commit `9420c78`; implemented and tested at about 01:00, before the 11:00 kill)
- **C1, haemoconcentration:** creatinine mass is conserved, Vd(t) = max(TBW - v_tot, 0.8 TBW) x 10 dL
  (`renal.creatinine_step`, `batch.creatinine_step_vec`).
  - Acceptance test: a 2 L loss over 9 h at constant GFR gives +2.9 % (matches the continuous ODE to 1e-4; v5 quoted
    "about +2.5 %").
  - With no water loss the result equals the old engine exactly.
- **C2, exertion:** GFR x (1 - k_ex x ex).
  - ex = lagged clip((met - 2) / 2, 0, 1). k_ex 0.25 [A, 0.10-0.40], tau_ex 1 h [A]; in the registry, not fitted.
  - The truth simulator has hidden per-patient values (lognormal around 0.25, uniform 0.5-2 h). The matched regime
    uses the registry values.
  - The existing episodic truth-only muscle-breakdown term is confirmed; no routine muscle term was added.
- **Effect on identical patients** (`reports/engine_revision_comparison.json`):
  - 2024 mismatched episodes 205 -> 216; matched 443 -> 449.
  - G2 morning values are slightly lower (e.g. triple +0.412 -> +0.390 mg/dL; the ordering is unchanged and the
    triple whammy still crosses first). Concentrated creatinine is also cleared faster, so after overnight
    rehydration the morning value ends a little lower.
- **L4 / L5 (revision-informed, `reports/literature_checks_l4_l5.json`):**
  - Ravi-like heavy shift: mean end-of-shift rise 0.003 (v1) -> 0.160 mg/dL (twin engine) and 0.165 (truth
    simulator), i.e. a cross-shift eGFR fall of about 16 % (Sorensen 2019: 21.8 %).
  - Cross-shift AKI share stays **0 %** against about 50 % in cane cutters. This was expected (v5 C2); k_ex was not
    raised.
  - The next 08:00 value is back to baseline, which supports the 08:00 rule.
  - L5 with sustained exertion: 34 / 38 / 40 % at 3 / 5 / 8 % loss vs Belli 25-44 %. Dehydration alone is unchanged
    (12 / 18 / 19 %, matching Chapman's ~12 %).
  - **Stated limitation:** the engine under-represents transient cross-shift creatinine rises in heavy outdoor
    workers.

### Cohort at 10,000 / 5,000 (commit `b61da13`, `reports/cohort_summary.json`)
- Train pool 10,000 (P...) for 2024; a separate test pool of 5,000 (T..., own seed) for 2025 and 2026. Generated in
  2,500-patient shards (only about 1 GB of RAM is free on the development machine).
- Mismatched episodes: 619 (2024), 317 (2025), 345 (2026). Size targets >= 500 / >= 250 are met.
- Label-positive eligible days: 0.14 % / 0.14 % / 0.16 %.
- **Heat-attributable fraction** (`reports/calibration_checks.json`, N = 10,000):
  - 9.9 % (95 % CI 5.8-13.7), ranging 7.4 % (sweat x0.7) to 16.3 % (x1.3) and 26.7 % under matched truth.
  - On the same 3,000 patients the revision moves it 13.2 % -> 15.3 % (CI 10.5-20.8). The 10,000-patient estimate
    is lower because of sampling: the CIs overlap.
  - **Office vs outdoor resolved:** office 0.0 % (CI -5.6 to 5.7), outdoor 12.7 % (CI 7.3-18.0), home 7.0 %. The cap
    saves office workers 27 L of season sweat vs 52 L for outdoor workers. The v1 office figure rested on about 25
    episodes.
- **L1 pooled 2024-26:** RR 2.30 (95 % CI 1.69-3.03), pass (`reports/l1_pooled.json`; patient-level bootstrap,
  400 resamples; constant calibrated once).
- **Demo personas** (`reports/demo_numbers.json`):
  - Kamala goes red at 43.5 % the day before her simulated AKI (23 h lead).
  - Kamala what-if: continue 48 % -> swap 25.5 % -> + ORS 1.5 % -> pauses 0 % (displayed "<1%").
  - Ravi stays green with a 0.13 mg/dL transient intra-day rise.

### Safety items, C3, C4 (commit `666bb17`)
- `config/red_flags.yaml` + `whatif/red_flags.py` run before any risk model:
  - **Emergency** (confusion, fainting, seizure, unresponsive or >= 40 degC): a 108 / 112 screen, no risk shown.
  - **Urgent** (no urine 12 h; cola urine + muscle pain after heat or work; vomiting with no fluids kept for 6 h):
    same-day doctor message, minimum level red.
  - EN / HI / KN / TE (HI / KN / TE are draft translations). Text check-in parsing via the lexicon.
  - Every flag is written to a new HMAC-chained audit log (`security/audit.py`; Part 6 adds checkpoints).
- ORS guardrails (`whatif/guardrails.py`, `config/guardrails.yaml`): with heart failure, eGFR < 30 or K >= 5.5 the
  advice becomes "Fluid type and amount as advised by your doctor".
- Display rules (`fastclock/display.py`):
  - "<1%" instead of 0 %, with a Wilson interval for Monte-Carlo risks;
  - lab eGFR tagged "not reliable while creatinine is changing";
  - "modelled filtration".
- C3: the Trichy penalty is "any AKI (yes/no), associated with", applied once. The extra-episode multiplier is an
  ASSUMPTION capped at 2.
- C4: heatstroke figure replaced with 67,637 / 374 (1 Mar-27 Jul 2024).
- `docs/MATH_CONTEXT.md` v0.2 is published with a changes list. v0.1 said "Euler" and "7-day min baseline"; the code
  uses the exact exponential and the §9.3 baseline.

### Real-data checks R1a / R1b (commit `c7a236d`, `reports/r1_validation.json`; held-out)
- **R1a:** 99.29 % agreement with mimic-code `aki_stage_creat` on 1,272 values / 140 stays: **pass**.
  - All 9 disagreements are creatinine rises of exactly 0.3 mg/dL that floating point reads as 0.2999...
  - A tolerance fix was tried, then **reverted pending the team's decision**. It makes the rise cases agree, but
    exposes 16 exact-1.5x cases that mimic-code's own floating-point arithmetic misses (98.58 %).
  - It changes 0 of 1.22 M synthetic patient-days, so only real lab input is affected.
- **R1b:** 24-h-ahead creatinine RMSE on 8,812 ICU pairs: kinetic filter 0.556 vs carry-forward 0.533 vs linear trend
  1.98 mg/dL.
  - Carry-forward wins (difference CI 0.011-0.038). On MIMIC alone the filter is level (0.391 vs 0.413, CI crosses 0).
  - Reported as it came out. The filter settings were fixed in the registry first.


## Part 4: Fast clock (16 Oct 2026; G3 written at 15:15 IST)

### Built
- `twin/batch_ukf.py`: N patients' UKFs at once. It matches the scalar `KidneyTwin` to 1e-8, so 20,000
  patient-seasons x 122 days took about 70 min per regime.
- `fastclock/features.py` + `scripts/build_features.py`: 61 observed-only features at 09:00.
  - Inputs: twin posterior, 50-draw Monte-Carlo risk on a NOISY city forecast, exposure, body, reports, drugs, static
    fields, labs.
  - **Core set of 25** for M, with monotone constraints.
  - Patient split of the 2024 pool: 60 / 10 / 15 / 15.
- `fastclock/train.py`:
  - baselines B0 (last-lab logistic), B1 (heat-index rule), B2 (triple + heat + eGFR points), B3 (plain LightGBM, raw
    inputs), B4 (twin physics risk);
  - M (core 25) and M_full (61, sensitivity row);
  - isotonic calibration; all of it on 2024 only.
- `fastclock/alerts.py`: red <= 0.5 and amber + red <= 3 notifications per 100 patient-days, with hysteresis and 72-h
  de-duplication. Tuned on the 2024 calibration split.
- `fastclock/explain.py`: native `pred_contrib`, top 3 reasons -> `reason.*` keys in EN / HI / KN / TE.
- `fastclock/metrics.py`: patient-level bootstrap (1,000). Paired AUPRC differences, alert-level sensitivity, alerts
  per AKI caught, time in red, PPV with its ceiling and at 1/10 and 1/50 prevalence, lead time by trigger gap.
- Tests: `test_batch_twin.py` (2), `test_fastclock.py` (12). The leakage test changes everything after day 6 and
  requires identical features up to day 6.
- Events per core feature (2024 train): 14.7 episodes / 42.6 positive days.

### Results (`reports/fastclock_eval_mismatched.json`, `reports/fastclock_eval_matched.json`, `reports/g3_decision.json`)
**Mismatched (headline) AUPRC, positive-day prevalence about 0.14 %:**

| | 2024 internal test | 2025 test | 2026 test |
|---|---|---|---|
| B0 last lab | 0.0073 | 0.0064 | 0.0112 |
| B1 heat rule | 0.0016 | 0.0015 | 0.0017 |
| B2 points | 0.0019 | 0.0019 | 0.0021 |
| B3 plain LightGBM | **0.0642** | **0.0261** | **0.0227** |
| B4 twin physics | 0.0114 | 0.0081 | 0.0069 |
| **M hybrid (core 25)** | 0.0262 | 0.0203 | 0.0130 |
| M_full (61) | 0.0512 | 0.0269 | 0.0229 |

**Matched (optimistic ceiling) AUPRC:**

| | 2024 internal test | 2025 test | 2026 test |
|---|---|---|---|
| B3 plain LightGBM | 0.179 | 0.172 | 0.175 |
| B4 twin physics | 0.154 | 0.172 | 0.129 |
| **M hybrid** | **0.216** | **0.217** | **0.199** |

**G3 (pre-registered rule A1.4): M leads.** On the 2024 internal-test patients M beats B0 / B1 / B2. Paired
differences +0.019 / +0.025 / +0.024; all CIs exclude 0.
- **M does NOT beat B3** on mismatched data: -0.038, CI -0.079 to -0.005. Per EVAL_PLAN 15.5 we say so.
- B3's edge comes mostly from the last lab creatinine ratio, which the core 25 leave out.

**Mismatched operational numbers for M (internal / 2025 / 2026):**
- red sensitivity 43 / 29 / 26 % per AKI episode;
- 16.5 / 18.7 / 22.1 red alerts per AKI caught;
- 0.35 / 0.28 / 0.32 red notifications and 0.83 / 0.52 / 0.67 red days per 100 patient-days;
- amber-or-red sensitivity 68 / 54 / 54 %;
- red-day PPV 3.9 / 3.8 / 3.1 % (ceiling 17-28 %); 0.3-0.4 % at 1/10 and 0.06-0.08 % at 1/50 prevalence;
- within-patient AUROC 0.64 / 0.59 / 0.58 (B3 0.58 / 0.55 / 0.57);
- calibration slope 0.98 / 0.97 / 0.65.

**Lead time (A1.3):** median 23 h, i.e. red at 09:00 the day before an 08:00 onset. On the >= 24 h-gap subset it is
also 23 h, so the pre-registered >= 24 h target is **not met**.
- The daily cadence makes "the day before" 23 h.
- 30-44 % of caught episodes were red 47 h or more ahead.

**By trigger (mismatched 2025 / 2026):**
- sick-day trigger >= 24 h before onset: 65 / 129 and 58 / 133 caught;
- no sick-day trigger: 22 / 173 and 27 / 195 caught.

**Age >= 75 (M):** AUPRC 0.049 / 0.024, red sensitivity 38 / 33 % (40 episodes each). Creatinine-defined AKI may be
under-detected in older people.

### Deviations, clarifications, open questions
1. **Lead-time definition:** first red day inside the 72-h prediction window. A red run that started earlier is not
   counted as a forecast. An earlier draft extended runs backwards; it was caught and fixed with a test before the
   final evaluation.
2. **Time in red** was added as a secondary operational metric.
   - B0 keeps 22 % of patient-days red (one high lab stays red for weeks), against 0.5-0.8 % for M.
   - The notification budget alone does not show this.
3. **Thresholds** were tuned on calibration data; on held-out data some models land slightly above the 0.5 red budget
   (matched B3 0.53 internal, M_full matched up to 0.54). Mismatched M stays within budget in every set.
4. **Open for the team:**
   - (a) R1a floating-point boundary choice (see the Decisions v4 / v5 section);
   - (b) whether a post-hoc model (adding the last-lab ratio to the core set, or M_full) should be considered, which
     would need an Amendment 3 and would make the 2025 / 2026 numbers no longer untouched;
   - (c) stating the 23-h lead as a missed target.


## Handover (18 Oct 2026, evening): environment on the new build machine

The build moved to a teammate's Windows machine. Python 3.12.10 (Python install manager), venv rebuilt from
`requirements.lock`. Two findings:
- **LightGBM crashed on every call** ("access violation reading 0x0000000000000000") because the machine's system
  Visual C++ runtime is old (`msvcp140.dll` 14.13). LightGBM 4.7 needs 14.40 or newer. `vrikka/__init__.py` now
  preloads the current runtime that scikit-learn's wheel bundles (Windows only; harmless elsewhere). The proper fix on
  such a machine is the latest Microsoft Visual C++ Redistributable (x64).
- With that, the untouched HEAD suite gives **148 tests: 147 pass, 1 skipped** (the MIMIC DuckDB data test; the
  validation database is not rebuilt on this machine).
- Regenerating `reports/demo_numbers.json` here reproduces every persona number except one Monte-Carlo value: S5's
  maximum risk is 0.005 instead of 0.0 (one of 200 draws; HEAD code on this machine gives the same 0.005, so it is a
  linear-algebra difference between machines, not a code change). Both display as "<1%".


## Part 5: Slow clock + what-if + guardrails (18 Oct 2026)

### Built
- `slowclock/bayes_slope.py`: conjugate Bayesian eGFR slope. Prior by group from the registry (no diabetes -1.5,
  diabetes -3.0, diabetes + UACR >= 30 mg/g -6.43 per year; SD 2.5; intercept SD 15); observation SD 5. Only stable
  eGFR values enter (`fastclock/display.lab_egfr_status`): values taken while creatinine is changing are skipped.
- `slowclock/projection.py`: 2,000 Monte-Carlo draws; 10-90 % ranges only; years to eGFR < 60 / 30 / 15 (">15 years"
  beyond the search horizon; eGFR floored at 0).
  - AKI penalty: `aki_slope_penalty` x stage multiplier x exp(-t / `aki_penalty_tau_years`), applied **once for any
    AKI**; extra episodes add `aki_penalty_extra_episode_mult`, at most `aki_penalty_max_episodes` (2) count. For a
    past episode only the part still to come is added. A future episode also adds the one-off step `aki_step_stageN`.
  - SGLT2i: initial dip `sglt2i_initial_dip`, then `sglt2i_slope_effect` per year. BP control and stopping a chronic
    NSAID use their registry ASSUMPTIONS.
  - The modifier parameters are drawn uniformly over their registry ranges, so the effect of an AKI or a treatment is
    itself a range (a fixed penalty gave a zero-width "range", which the ranges-only rule forbids).
  - Wording keys: "associated with", "extrapolated" for people without diabetes, ranges only.
- `slowclock/kfre.py`: KFRE only for eGFR 10-59 with a UACR (male centering as published); otherwise the reason.
- `whatif/levers.py` + `config/whatif.yaml`: levers in the agreed order (painkiller swap -> ORS / work-hour shift ->
  drug pauses last with the badge "individualised, weak evidence (Think Kidneys 2018), clinician decides"), common
  random numbers, guardrail status per lever; never-levers are never offered.
- `whatif/guardrails.py` (extended): paracetamol ceiling across brands, potassium (>= 6.0 same-day repeat + clinician
  alert; >= 5.5 caution on every lever), heart failure + diuretic pause warning, co-trimoxazole never suppresses AKI,
  exclusions (< 18, pregnancy, eGFR < 15 / dialysis). Thresholds in `config/guardrails.yaml`.
- `whatif/sickday.py`: sick-day guidance, generic names, "ask your doctor whether to pause ..." (never "stop").
- `twin/replay.py`: optional `capture_day` keeps the twin and its 72-h inputs for a live what-if (no number changes).
- `config.overrides()`: temporary registry values inside their registered ranges (tests, tornado).
- i18n: alert levels, actions, levers, pause reasons, guardrails, exclusions, sick-day, KFRE and slow-clock text in
  EN / HI / KN / TE (HI / KN / TE remain "draft translation").
- `docs/CLINICAL_SAFETY.md`: intended use, exclusions, red flags, guardrails, display rules, limitations, hazard log.
- Scripts: `validate_r3.py` -> `reports/r3_tawam.json`; `make_slowclock_demo.py` -> `reports/slowclock_demo.json`.
- Tests: `test_slowclock.py` (15), `test_whatif.py` (23, including the Kamala lever table reproducing
  `reports/demo_numbers.json` exactly: 0.48 -> 0.255 -> 0.015 -> 0.0).

### Results
- **R3 (held-out; `reports/r3_tawam.json`):** Tawam, 491 patients, 56 reached eGFR < 60. C-index of the slow clock's
  years-to-60: **0.836 (95 % CI 0.776-0.889)**; baseline eGFR alone **0.834 (0.783-0.877)**; paired difference CI
  -0.036 to 0.032. The slow clock ranks progression **as well as baseline eGFR alone, not better**: without serial
  eGFR, its only extra input is the diabetes prior. KFRE: not applicable (all eGFR >= 60, no UACR).
- **Personas (`reports/slowclock_demo.json`):** with the baseline eGFR as the only observation the 10-year ranges are
  wide (e.g. Kamala 9.6-75.5 mL/min/1.73 m2, median 43.3); one stage-1 kidney injury this season is associated with
  a 10-year difference of -7.8 to -2.9 (median -5.1) under the registry assumptions.

### Decisions and deviations
1. `sglt2i_slope_effect` 1.4 (VERIFY) -> **1.37 (CITED, EMPA-KIDNEY, range 1.16-1.59)**, as Amendment 2 A2.2 already
   recorded. This is an input to the slow clock, not a fitted value.
2. New registry entries: `projection_step_years`, `slow_mc_draws`, `slow_band_low_q` / `slow_band_high_q`, KDIGO
   thresholds 60 / 30 / 15, `albuminuria_uacr_mg_g`, and the lever settings `whatif_ors_l_day` (1 L/day, the demo's
   value) and `whatif_work_start_hour` (06:00).
3. Personas gained `generics` (generic names) and `history` (diabetes, UACR, heart failure, last potassium) in
   `config/scenarios.yaml`. Mr Iyer now has heart failure (his label says so) so the heart-failure guardrails can be
   shown; this does not change any replay number.
4. Open team decisions unchanged and left at the science-preserving default: model M (no Amendment 3), the
   pre-registered KDIGO comparison, and the lead time stated as missed.


## Part 6: Services + trust layer (18 Oct 2026)

### Built
- `services/` (one layer for every page and API call): role allowed? -> own record for patient / family -> signed,
  unexpired consent artefact for every other role, **checked on every read** -> audit entry (allowed or denied, with
  the reason) -> only the role's fields leave; names are Fernet-encrypted at rest and decrypted only for roles that
  may see them. `services/directory.py`: the six fictional personas (twin simulation, display bands) and the triage
  panel (frozen model M), every number from `reports/`.
- `security/`: `rbac.py` (doctor, patient, family, ASHA, lab, admin; field filtering), `auth.py` (bcrypt demo logins
  from `.env`, PyJWT tokens), `consent.py` + `interop/abdm_consent.py` (ABDM-style artefact: purpose, requester,
  health-information types, access mode, date range, expiry, status; Ed25519-signed; revoke), `audit.py` (Ed25519-signed
  checkpoints on top of the HMAC chain, `first_bad_index`, tamper demo), `device_gateway.py` (plausibility, weight
  jumps, stale / future time stamps, replayed nonces, Ed25519 device signatures; rules in `config/integrity.yaml`),
  `crypto.py`, `dpdp.py` (DPDP Act 2023 mapping table; a design mapping, not legal advice).
- `interop/fhir_export.py` + `loinc.py`: FHIR R4 collection Bundle (Patient, LOINC Observations, RiskAssessment,
  Consent) with a structural validator.
- `store/`: SQLite (stdlib) for kidney-test orders, lab results and check-ins; free text encrypted.
- `api/`: thin FastAPI wrapper over the same services (bearer tokens); `uvicorn vrikka.api.main:app`.
- `fastclock/frozen.py`: the one place that loads the frozen Part 4 models, isotonic maps and thresholds.
- Tests: `test_trust.py` (14): **S10** implausible / jumping / replayed / stale / unsigned feeds rejected and audited;
  **S11** revoked consent blocks doctor reads, triage listing and FHIR export, and is audited; consent signature,
  expiry and scope; role filtering; own-record rule; order -> lab result -> purple level; potassium alert; check-in
  runs red flags first and stores text encrypted; tamper demo (a re-chained forgery passes the HMAC chain but fails
  the signed checkpoint); FHIR validity; DPDP coverage; the API enforces the same rules.

### Results
- **R4 (secondary line; `reports/r4_pmdata.json`):** 13 of the 16 PMData people have enough data (at least 14 resting
  HR days and 5 weights); 1,845 person-days in Norway, Nov 2019 - Mar 2020. Frozen M with its frozen thresholds:
  **0 red and 0 amber notifications** (maximum calibrated probability 0.00143 against a red threshold of 0.0133); the
  twin's own 72-h simulation never reached the 5 % display band (maximum 0.04). Caveats in the report (Fitbit's
  smoothed resting HR, whole-kilogram weights, winter, back-calculated baseline).
- **Cohort reproducibility:** `scripts/generate_cohort.py` on this machine reproduces `reports/cohort_summary.json`
  exactly and leaves the committed 20-patient sample unchanged.

### Decisions and deviations
1. The app calls the services in-process (`APP_MODE=inprocess`, now the default); the FastAPI wrapper is optional.
2. Personas keep the twin's 72-h simulation with the display bands (5 % / 15 %); the frozen Part 4 thresholds belong to
   the calibrated model M. Under the frozen B4 thresholds every day would be amber (the notification budget counts
   new notifications, so a constant amber costs one notification per patient), so they are not used for display.
3. Mr Iyer is the heart-failure persona (ORS guardrail and diuretic-pause warning); Kamala's CYP2C9 variant is named
   "Kamala, CYP2C9 *3/*3 variant".
4. The ABDM pattern is demonstrated, not integrated: no ABDM sandbox or gateway is called.
