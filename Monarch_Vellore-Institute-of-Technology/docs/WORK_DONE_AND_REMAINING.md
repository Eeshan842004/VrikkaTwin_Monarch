# VrikkaTwin: what has been done and what is left

Team Monarch (Harshita Kumar, Eeshan Gupta), Vellore Institute of Technology · Happiest Health Digital Twin Challenge
2026 · official deadline **Tue 20 Oct 2026, 19:00 IST**. Status as of 20 Oct 2026. Every number quoted here comes from
a file in `reports/` (named next to it); the full build log is `PROGRESS.md` and the hand-off page is `STATUS.md`.

---

## 1. Summary

| Area | Status |
|---|---|
| Parts 1-4 (foundation, physiology engine, twin + synthetic world, fast clock) | Done before the handover |
| Part 5: slow clock, what-if levers, clinical guardrails, safety case, R3 | **Done** |
| Part 6: services + trust layer (consent, RBAC, audit, integrity gate, FHIR, API), R4 | **Done** |
| Part 7: 8 app pages + full evaluation (reproduction, robustness, subgroups, tornado) | **Done** |
| Part 8: README, docs, diagrams, slides, draft video, Dockerfile, presentation facts, screenshots | **Done** |
| Optional features a, b, c (twin fit panel, Kidney Weather, visit summary) | **Done** |
| Persona renamed Kamala -> Riya; team line "Harshita Kumar and Eeshan Gupta" | **Done** |
| All code pushed to `origin/main` (github.com/Eeshan842004/VrikkaTwin_Monarch, public) | **Done** |
| Live demo video, hosted deployment, native-speaker / clinician review, Unstop submission | **Left for the team** (section 4) |

Tests: 219 collected, **218 pass, 1 skipped** (the skipped test needs the MIMIC DuckDB, rebuilt by
`scripts/build_validation_duckdb.py`). Lint (`ruff`): clean. Run the app: `.venv/Scripts/python -m streamlit run
app/Home.py` -> http://localhost:8501 (one-click demo logins in the sidebar).

---

## 2. What was done, step by step

### 2.1 Handover and environment (18 Oct)
- Read STATUS, PROGRESS, EVAL_PLAN, MATH_CONTEXT, DATA_SEARCH; checked the code, reports and git log.
- Installed Python 3.12 (Python install manager) and rebuilt `.venv` from `requirements.lock`.
- Found and worked around a crash: LightGBM failed on every call because this PC's Visual C++ runtime is old.
  `src/vrikka/__init__.py` now loads the newer runtime bundled with scikit-learn first (permanent fix: install the latest
  Microsoft Visual C++ Redistributable x64).
- Verified the handover claim: the original code gives 148 tests (147 pass, 1 skipped).
- Re-generated the synthetic cohort and the 2025 / 2026 test features: `reports/cohort_summary.json` and every reported
  held-out AUPRC were **reproduced exactly** (`reports/evaluation_extras.json`, `reproduction`).

### 2.2 Part 5: slow clock, what-if, guardrails
- `src/vrikka/slowclock/`: Bayesian eGFR slope (registry priors by diabetes / albuminuria), 10-90 % ranges only,
  AKI penalty applied once and fading ("associated with"), SGLT2i effect as an input, KFRE only where valid.
- `src/vrikka/whatif/`: levers in the agreed order (painkiller swap -> ORS / work hours -> medicine pauses last, badged
  "clinician decides"); guardrails for ORS, paracetamol ceiling, potassium (>= 6.0 same-day repeat), heart failure +
  diuretic pause, co-trimoxazole never suppresses AKI, exclusions (< 18, pregnancy, eGFR < 15 / dialysis); sick-day
  guidance that never says "stop your medicine".
- `docs/CLINICAL_SAFETY.md`: intended use, red flags, guardrails, limitations, hazard log.
- **R3** (Tawam, `reports/r3_tawam.json`): slow-clock C-index 0.836 vs baseline eGFR alone 0.834 - as good, not better.

### 2.3 Part 6: services and trust layer
- One services layer for the app and the API: role -> own record / signed consent artefact (checked on every read) ->
  audit -> field filtering; names and free text encrypted at rest.
- ABDM-style consent with one-click revoke (test S11); HMAC hash-chained audit log with Ed25519-signed checkpoints and a
  tamper demo; data-integrity gate for device readings (test S10); FHIR R4 export; DPDP Act 2023 mapping; FastAPI.
- **R4** (PMData, `reports/r4_pmdata.json`): 13 healthy people, 0 false red alerts.

### 2.4 Part 7: app and full evaluation
- Eight Streamlit pages: Doctor Triage, Patient Twin, Patient and Family (EN / HI / KN / TE + pre-generated audio),
  ASHA Field (Telugu by default), Lab Tasks, Trust Center, Time Machine, Evaluation (reality checks by category).
- `reports/evaluation_extras.json`: robustness (no wearable band, everyone Tier 0, missing data, noise x2, perfect
  forecast - all confidence intervals overlap the headline), subgroups, and a tornado over 81 registry assumptions
  (drinking fraction ranks 3rd).

### 2.5 Part 8: deliverables
- `README.md` generated from the reports (`scripts/make_readme.py`); `docs/DESIGN.md`, `docs/NUMBERS_CHECKED.md` (16
  external facts checked against their sources; two citations corrected), `docs/VIDEO_SCRIPT.md`, `docs/DEPLOY.md`.
- `deliverables/`: `architecture.pdf`, `daily_flow.pdf`, `VrikkaTwin_slides.pptx` / `.pdf` (numbers from the reports),
  `VrikkaTwin_overview.mp4` (4-minute narrated draft), `screenshots/` (14 PNGs), `docker/Dockerfile`.
- `PPT_FACTS.md` in the repository root (gitignored, `scripts/make_ppt_facts.py`): every fact for the slides with its
  source file.

### 2.6 Final task list (19 Oct)
- Kamala -> Riya everywhere (reports regenerate byte for byte).
- Summary reports for the slides: `reports/metrics.json`, `reports/reality_checks.json`, `reports/feature_importance.json`.
- Optional a: "How well does the twin know this patient?" (`reports/twin_fit.json`).
- Optional b: Tomorrow's Kidney Weather on Doctor Triage (`reports/demo_triage_panel.json`, `kidney_weather`).
- Optional c: one-click printable visit summary in the patient's language with the disclaimer.

---

## 3. Headline results (all synthetic unless stated; sources in brackets)

| Result | Value | Source |
|---|---|---|
| Pre-registered G3 rule | hybrid model M leads (beats baselines B0 / B1 / B2) | `reports/g3_decision.json` |
| M internal-test AUPRC (prevalence about 0.14 %) | 0.0262 (95 % CI 0.0117-0.0543) | `reports/g3_decision.json` |
| Plain LightGBM B3 | 0.0642: **beats M on the mismatched world** (stated) | `reports/g3_decision.json` |
| Median lead time (target >= 24 h) | 23 h: **target missed** | `reports/g3_decision.json` |
| R1a labelling vs official MIMIC code (real data) | 99.29 % agreement: pass | `reports/r1_validation.json` |
| R1b 24-h creatinine forecast (real data) | carry-forward 0.532 beats our filter 0.556 mg/dL | `reports/r1_validation.json` |
| R3 slow clock (real data, Tawam) | 0.836 vs 0.834 for eGFR alone | `reports/r3_tawam.json` |
| R4 false alarms (real data, PMData) | 0 red alerts | `reports/r4_pmdata.json` |
| Riya (fictional) | red the morning before her simulated injury; painkiller swap and ORS lower the risk | `reports/demo_numbers.json` |

---

## 4. What is left (needs a person or the team's accounts)

| # | Task | Who | How |
|---|---|---|---|
| 1 | Record the live demo video and upload it (unlisted YouTube) | team | follow `docs/VIDEO_SCRIPT.md`; paste the link into `VIDEO_URL` in `scripts/make_readme.py`, run `python scripts/make_readme.py`, commit and push |
| 2 | Submit on Unstop before **20 Oct, 19:00 IST** | team leader | repository link + video link + slides PDF |
| 3 | Check every README link while logged out of GitHub | team | open the repository in a private window |
| 4 | (Optional) hosted demo | team | `docs/DEPLOY.md` (Hugging Face Spaces, Docker); the image has not been built yet because Docker is not installed on the build PC |
| 5 | Native-speaker review of the Hindi, Kannada and Telugu text | team / reviewers | `config/i18n/*.yaml` (marked "draft translation") |
| 6 | Clinician sign-off of the two URGENT red-flag messages | clinician | `config/red_flags.yaml` (`clinical_wording: VERIFY`) |
| 7 | Open science decisions (defaults kept) | team | KDIGO floating-point boundary, model choice (M kept), lead-time wording ("missed") - `STATUS.md` section 5 |
| 8 | Permanent fix for the LightGBM crash on the build PC | owner of the PC | install the latest Microsoft Visual C++ Redistributable (x64; admin rights) |

Not built on purpose (by decision): live speech recognition in the hosted app, the potassium model (stretch goal),
an ABDM gateway integration (the consent pattern is demonstrated), an LLM chatbot, OCR.

---

## 5. Known limitations to state in the pitch

Synthetic validation only; creatinine rises only after filtration has fallen; the 24-h lead-time target was missed; a
plain LightGBM beat the hybrid model on the mismatched world; carry-forward beat our kinetic filter on real ICU data;
heavy outdoor workers' cross-shift creatinine rises are under-represented (L4); the wearable band added no measurable
value in the synthetic world; translations and two urgent messages await review; not a medical device. Details:
`docs/CLINICAL_SAFETY.md` section 6.
