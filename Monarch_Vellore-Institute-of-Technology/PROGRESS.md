# VrikkaTwin build log

Team Monarch, Vellore Institute of Technology. The build follows the team's design plan in 8 parts, with a stop after each part. Every entry records what was built, the test results, key numbers (with their source file), decisions, deviations from the plan, open issues and commit hashes.

| Part | Phases | Gate | Status |
|---|---|---|---|
| 1 Foundation | P0 + P1 | G0, G1 | **done** (G0 `ef100fe`, G1 see below) |
| 2 Physiology engine | P2 | G2 | not started |
| 3 Twin + synthetic world | P3 ‖ P4 | exit checks | not started |
| 4 Fast clock | P5 | G3 | not started |
| 5 Slow clock + what-if | P6 + P7 | exit checks | not started |
| 6 Backend + trust layer | P8 | G4 | not started |
| 7 Frontend + evaluation | P9 ‖ P10 | G5 freeze | not started |
| 8 Deliverables + submission | P11 | G6 | not started |

---

## Part 1: Foundation (P0 + P1)

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
