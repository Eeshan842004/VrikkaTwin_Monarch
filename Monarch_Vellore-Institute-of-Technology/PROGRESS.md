# VrikkaTwin build log

Team Monarch, Vellore Institute of Technology. The build follows the team's design plan in 8 parts, with a stop after each part. Every entry records what was built, the test results, key numbers (with their source file), decisions, deviations from the plan, open issues and commit hashes.

| Part | Phases | Gate | Status |
|---|---|---|---|
| 1 Foundation | P0 + P1 | G0, G1 | **done** (G0 `ef100fe`, G1 see below) |
| 2 Physiology engine | P2 | G2 | **done** (G2, see below) |
| 3 Twin + synthetic world | P3 ‖ P4 | exit checks | not started |
| 4 Fast clock | P5 | G3 | not started |
| 5 Slow clock + what-if | P6 + P7 | exit checks | not started |
| 6 Backend + trust layer | P8 | G4 | not started |
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
