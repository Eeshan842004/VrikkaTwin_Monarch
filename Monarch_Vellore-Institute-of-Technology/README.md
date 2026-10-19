# VrikkaTwin: a kidney digital twin for heatwaves and sick days

**Team Monarch, Vellore Institute of Technology** · Happiest Health Digital Twin Challenge 2026
Team: Eeshan, Harshita Kumar.

VrikkaTwin warns of **acute kidney injury (usually mild, usually recovers)** up to **72 hours ahead** for people with
hypertension or chronic kidney disease during heatwaves and sick days, shows the safer choices that lower that risk,
and projects long-term kidney function as honest ranges. It is a research prototype tested on synthetic patients and
open datasets: **not a medical device**; every person shown is synthetic or fictional.

| Deliverable | Where |
|---|---|
| Video (demo walkthrough) | VIDEO LINK: add the unlisted YouTube URL here after upload (script: [`docs/VIDEO_SCRIPT.md`](docs/VIDEO_SCRIPT.md)) |
| Architecture diagram (PDF) | [`deliverables/architecture.pdf`](deliverables/architecture.pdf) |
| Presentation (PDF / PPTX) | [`deliverables/VrikkaTwin_slides.pdf`](deliverables/VrikkaTwin_slides.pdf) · [`.pptx`](deliverables/VrikkaTwin_slides.pptx) |
| Licence | [MIT](LICENSE) (code); data licences in [`data/README.md`](data/README.md) |
| Design notes · safety case · facts checked | [`docs/DESIGN.md`](docs/DESIGN.md) · [`docs/CLINICAL_SAFETY.md`](docs/CLINICAL_SAFETY.md) · [`docs/NUMBERS_CHECKED.md`](docs/NUMBERS_CHECKED.md) |
| Pre-registered evaluation plan · build log | [`reports/EVAL_PLAN.md`](reports/EVAL_PLAN.md) · [`PROGRESS.md`](PROGRESS.md) |

## The problem and the use case

Heat and sick days dry the body out. Add a blood-pressure medicine of the ACE-inhibitor / ARB type, a water tablet
and a painkiller such as ibuprofen (the "triple whammy": kidney-injury rate ratio 1.31, and 1.82 in the first 30 days;
Lapi et al., BMJ 2013) and the kidneys can lose their self-protection. In India's 2024 heat season NCDC surveillance
recorded 67,637 suspected heatstroke cases and 374 deaths (1 Mar - 27 Jul 2024; Lok Sabha reply). Kidney injury in
these episodes is silent at home: creatinine is rarely measured at the right time.

- **Doctor:** which of my patients needs a creatinine test today, and why?
- **Patient and family:** what should I do today, in my language (English, Hindi, Kannada, Telugu, with audio)?
- **ASHA worker:** are there warning signs that cannot wait (a Tier-0 form, Telugu by default)?
- **Lab:** home kidney test orders and results.

## How it works

![architecture](deliverables/architecture.png)

1. **Personal twin.** An Unscented Kalman Filter over body water (total and extracellular deficit), creatinine, a
   personal sweat multiplier and dry weight, updated every morning from the weight and resting heart rate (missing
   readings allowed; a weekly ASHA weight is enough for Tier 0). Heat exposure comes from the ISO 7933 heat-strain
   model on real Open-Meteo weather and the person's routine; drugs act with their own effect half-lives; creatinine
   follows mass-conserving kinetics.
2. **Fast clock.** Every morning the twin simulates the next 72 hours 200 times on a noisy
   forecast and applies the same KDIGO rule (one 08:00 creatinine a day) used for the labels. A hybrid model M
   (LightGBM, 25 monotone core features out of 61) turns this into a calibrated risk with its top-3
   reasons. Alerts are budgeted in advance: red at most 0.5 and amber + red at most
   3 notifications per 100 patient-days.
3. **What-if.** Levers in a fixed order (painkiller swap, then ORS and work hours, then medicine pauses last, which the
   clinician decides), all simulated with the same random draws.
4. **Slow clock.** A Bayesian eGFR slope with registry priors; 10-90 % ranges only; the AKI penalty
   is "associated with" (one Indian diabetic kidney disease cohort, n = 274), applied once and fading; KFRE only where
   valid.
5. **Safety and trust.** Red flags run before any model (heatstroke: call 108 / 112). Guardrails on ORS, paracetamol,
   potassium, heart failure and co-trimoxazole. One services layer checks the role and a signed ABDM-style consent
   artefact on every read and writes a hash-chained audit log with Ed25519-signed checkpoints; device readings pass a
   data-integrity gate; FHIR R4 export; DPDP Act 2023 mapping.

The synthetic world that generates the training and test data is kept apart from the model (the model packages never
import it, a test enforces this). The headline evaluation uses a **mismatched** world whose truth equations differ from
the twin's.

## Results (all numbers read from `reports/*.json`)

Enriched high-risk heat-season cohort: 10,000 training patients (2024 season) and
5,000 separate test patients (2025 and 2026 seasons); 619
/ 317 / 345 kidney-injury episodes
(mismatched world); positive-day prevalence 0.14 %.

**AUPRC on the mismatched world** (2024 internal test / 2025 held-out / 2026 held-out):

| Model | 2024 | 2025 | 2026 |
|---|---|---|---|
| B0 last lab | 0.0073 | 0.0064 | 0.0112 |
| B1 heat-index rule | 0.0016 | 0.0015 | 0.0017 |
| B2 points score | 0.0019 | 0.0019 | 0.0021 |
| B3 plain LightGBM | 0.0642 | 0.0261 | 0.0227 |
| B4 twin physics only | 0.0114 | 0.0081 | 0.0069 |
| **M hybrid (lead)** | 0.0262 | 0.0203 | 0.0130 |
| M_full (sensitivity) | 0.0512 | 0.0269 | 0.0229 |

- **Pre-registered rule (G3): M leads**: it beats B0 / B1 / B2 (paired differences
  +0.0189 / +0.0246 /
  +0.0243, all CIs exclude 0).
- **A plain LightGBM (B3) beats M on the mismatched world** (paired difference -0.0380,
  CI -0.0789 to -0.0047). M wins on the matched world
  (0.216 vs
  0.179) and is the model the what-if runs on.
- **Operational (M, red):** catches 43 /
  29 / 26 % of injury episodes
  with 16.5 / 18.7 /
  22.1 red alerts per injury caught (2024 / 2025 / 2026).
- **Lead time:** median 23 h. **The pre-registered target of at least 24 h was
  missed** (one prediction a day at 09:00 against an 08:00 onset makes "the day before" read just under 24 h).
- **Kamala (fictional persona):** red at 43.5 % the morning before
  her simulated injury; what-if: continue 48.0 % -> painkiller swap 25.5 % -> + ORS
  1.5 % -> + pauses <1 %; same tablets with CYP2C9 *3/*3 55.5 %.

**Reality checks on real data and literature**

| Check | Category | Result |
|---|---|---|
| R1a labelling vs official mimic-code KDIGO (MIMIC-IV demo) | held-out | 99.29 % agreement: pass |
| R1b 24-h creatinine forecast (MIMIC + eICU demos) | held-out | kinetic filter 0.556 vs carry-forward 0.532 mg/dL RMSE: **carry-forward wins** |
| R3 slow-clock ranking (Tawam, 491 patients) | held-out | C-index 0.836 vs baseline eGFR alone 0.834: as good, not better |
| R4 false alarms on healthy people (PMData, 13 people) | held-out | 0.0 red notifications per 100 person-days |
| L1 triple vs double therapy | calibration | RR 2.3 (1.69-3.03), band 1.1-2.5: pass |
| Heat share of injuries | calibration | about 7-27 % depending on assumptions (central 9.9 %) |
| L4 cross-shift AKI in a heavy outdoor worker | revision-informed | 0 % vs about half of cane cutters: **stated limitation** |

**Robustness** (2025 held-out season, the same 2500 test patients in every row; frozen
model, nothing retuned):

| Variant | AUPRC | Red sensitivity | Red per 100 patient-days | Median lead (h) |
|---|---|---|---|---|
| Headline (noisy forecast) | 0.0178 | 28 % | 0.28 | 23.0 |
| Perfect forecast | 0.0169 | 26 % | 0.204 | 23.0 |
| No wearable band | 0.0231 | 26 % | 0.221 | 23.0 |
| Everyone Tier 0 (weekly ASHA weight) | 0.0209 | 24 % | 0.204 | 23.0 |
| 30 % of band days missing | 0.0169 | 28 % | 0.262 | 23.0 |
| 50 % of band days missing | 0.0183 | 28 % | 0.255 | 23.0 |
| Sensor noise x2 | 0.0157 | 28 % | 0.323 | 23.0 |

Sensitivity: 81 registry assumptions screened on Kamala's 72-h risk; the drinking fraction ranks 3. Re-generating the cohort and features on a second machine reproduces the reported held-out AUPRC: yes.

Full details, subgroups and categories: the **Evaluation** page of the app and [`PROGRESS.md`](PROGRESS.md).

## Run it locally

Requirements: Python 3.12 (Windows, macOS or Linux).

```bash
cd Monarch_Vellore-Institute-of-Technology
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.lock      # macOS / Linux: .venv/bin/python
.venv/Scripts/python -m pip install -e . --no-deps
.venv/Scripts/python -m streamlit run app/Home.py            # http://localhost:8501
.venv/Scripts/python -m uvicorn vrikka.api.main:app          # optional API: http://127.0.0.1:8000/docs
```

Use the one-click demo logins in the sidebar (doctor, patient, family, ASHA, lab, admin; passwords in `.env.example`).
Everything the app shows is already in the repository (`reports/`, `models/`, `data/weather/`, the fictional personas).
To rebuild the synthetic world and every report: `scripts/generate_cohort.py`, `scripts/build_features.py`,
`scripts/train_fastclock.py` (do not retune on 2025 / 2026), then the checks listed in `PROGRESS.md`; public datasets
come from `scripts/download_public_data.py`. Tests: `.venv/Scripts/python -m pytest`; lint: `ruff check .`.

Windows note: if LightGBM fails with "access violation reading 0x0000000000000000", the system Visual C++ runtime is
older than LightGBM needs; the package preloads the runtime bundled with scikit-learn, and the latest Microsoft Visual
C++ Redistributable (x64) fixes it permanently.

## Tech stack and model details

Python 3.12 · NumPy, SciPy, pandas, PyArrow · filterpy (UKF) · pythermalcomfort (ISO 7933 PHS) · LightGBM,
scikit-learn, lifelines · kfre · Streamlit, Plotly · FastAPI, Uvicorn · cryptography (Fernet, Ed25519), PyJWT, bcrypt ·
DuckDB (mimic-code KDIGO SQL) · gTTS (pre-generated audio) · rapidfuzz. Every model constant is in
`config/parameters.yaml` with its unit, range, provenance and source. Model details: `docs/DESIGN.md`,
`docs/MATH_CONTEXT.md`.

## Repository layout

```
src/vrikka/      physiology · twin · fastclock · slowclock · whatif · services · security · interop · store · api
                 simulator (synthetic world; never imported by the model packages)
app/             Streamlit pages
config/          parameter registry, clinical rules, drug lexicon, languages
scripts/         data, cohort, features, training, checks, reports, slides
reports/         every number the app, README and slides quote
deliverables/    architecture diagram, slides
tests/           unit, safety, trust, app and scenario tests
```

## Data and licences

Code: MIT. Weather: Open-Meteo (CC BY 4.0). Real-data checks: MIMIC-IV and eICU-CRD demos (ODbL; not redistributed),
UCI CKD, Tawam (PLoS ONE) and PMData (CC BY 4.0; not redistributed). Synthetic cohort generated by our code. Details:
[`data/README.md`](data/README.md), [`docs/DATA_SEARCH.md`](docs/DATA_SEARCH.md).

## Limitations

Synthetic validation only; creatinine rises only after filtration has fallen; the lead-time target was missed; a
plain LightGBM beat the hybrid model on the mismatched world; carry-forward beat our kinetic filter on real ICU data;
heavy outdoor workers' transient rises are under-represented; Hindi, Kannada and Telugu text and two urgent messages
await review. See [`docs/CLINICAL_SAFETY.md`](docs/CLINICAL_SAFETY.md).
