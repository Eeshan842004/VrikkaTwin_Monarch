# VrikkaTwin: build status and handoff

Last updated 18 Oct 2026. Read this first if you are picking up the build. `PROGRESS.md` has the full log with every
number and its source file; `reports/EVAL_PLAN.md` is the pre-registered evaluation plan (Amendments 1 and 2).

**Deadlines:** team target is to submit on **Sun 18 Oct 2026, 16:00 IST**; the official Unstop deadline is
**20 Oct 2026, 19:00 IST**.

---

## 1. Where things stand

| Part | What | Status | Commits |
|---|---|---|---|
| 1 | Skeleton, registry, configs, CI, licence, pre-registered eval plan, weather + public data | Done | `ef100fe`, `1b7f671`, `48e1546`, `a03ff11` |
| 2 | Physiology engine (CKD-EPI, KFRE, KDIGO, heat/sweat, renal model, NSAID PK) | Done | `723fd83` |
| 3 | Personal twin (UKF), Monte-Carlo risk, synthetic world, cohort | Done | `9821fd6`, `8945e96` |
| Pre-4 | Amendment 2, engine revision (haemoconcentration + exertion), safety layer, 10k / 5k cohort, R1a / R1b | Done | `09a8617` ... `c7a236d` |
| 4 | Fast clock: features, baselines, hybrid model, alerts, G3 decision | **Done** | `d101a2b`, `fe36277` |
| 5 | Slow clock + what-if levers + guardrails + clinical safety doc + R3 | **Done** | see `git log` |
| 6 | Services layer + security / trust layer | **Not started** (audit log core exists) | |
| 7 | Streamlit pages + full evaluation | **Not started** (page stubs only) | |
| 8 | README, docs, diagram, slides, video, deploy, go public, submit | **Not started** | |

Tests: **186 collected, 185 pass, 1 skipped** (the MIMIC DuckDB data test; rebuild it with
`scripts/build_validation_duckdb.py`), ruff clean.

---

## 2. How to run

- Windows, Python **3.12** venv at `.venv` (shap needs 3.12). Install: `pip install -r requirements.lock`, then
  `pip install -e . --no-deps`. If Python 3.12 is missing: `pymanager install 3.12` (Python install manager).
- Run everything from this folder: `.venv/Scripts/python <script>`. `python tasks.py <target>` mirrors the Makefile;
  `python tasks.py test` runs the CI subset.
- CI: `.github/workflows/ci.yml` at the repo root (ruff + fast tests).
- Regenerate data (gitignored; only `data/synthetic/sample/` and `demo_patients.json` are committed):
  1. `scripts/download_public_data.py`, then `scripts/build_validation_duckdb.py` (MIMIC / eICU demos; slow, PhysioNet throttles)
  2. `scripts/generate_cohort.py` (about 9 min; 10,000 train + 5,000 test patients, 2,500-patient shards)
  3. `scripts/build_features.py` (about 70 min per regime; writes `data/features/`)
  4. `scripts/train_fastclock.py` (about 10 min; writes `models/` and `reports/fastclock_eval_*.json`, `reports/g3_decision.json`)
  5. Checks: `calibration_checks.py`, `l1_pooled.py`, `validate_l4_l5.py`, `validate_r1.py`, `make_demo_patients.py`,
     `physiology_scenarios.py`, `compare_engine_revision.py`
- Gotchas:
  - The machine had only about 1 GB of free RAM; the generators work in shards for that reason.
  - pandas 3 stores "no diuretic" as NaN: use `simulator.ground_truth.diuretic_name()`.
  - Git Bash heredocs containing apostrophes break; write long files with an editor or Python.
  - LightGBM: use `lgb.train`.
  - LightGBM "access violation reading 0x0000000000000000" = an old system Visual C++ runtime (`msvcp140.dll` < 14.40).
    `vrikka/__init__.py` preloads scikit-learn's bundled runtime; the real fix is the latest VC++ Redistributable (x64).

---

## 3. Working rules (keep them)

1. Stop after every part with a plain-English report; the next part starts on the team's "go".
2. If an instruction conflicts with the code or data, stop and ask before changing the science.
3. Every model constant lives in `config/parameters.yaml` (value, unit, range, provenance, source). No hard-coded numbers.
4. **No hand-typed numbers**: every number in the UI, README, slides and video comes from `reports/*.json`.
5. The twin, fast clock, slow clock, what-if, API and physiology packages must never import `vrikka.simulator`
   (enforced by a test).
6. Patient text never says "stop your medicine"; personas are marked "(fictional)"; no sponsor logos; generic drug
   names first; never write "kidney failure" for these episodes; never show "0%" (show "<1%").
7. 2025 / 2026 test seasons are already used once for the Part 4 report: do **not** retune anything on them.
8. Keep `PROGRESS.md` updated. Commit messages: short human subject + 1-2 sentences, ending with the Co-Authored-By line.

---

## 4. Key results so far (all from `reports/`)

- **Cohort** (`cohort_summary.json`): 619 / 317 / 345 AKI episodes in 2024 / 2025 / 2026 (mismatched); ~0.14 % of
  eligible days are label-positive; almost all stage 1.
- **Heat share** (`calibration_checks.json`): about 10 % (95 % CI 6-14 %), 7-27 % across assumptions. Quote it as a range.
- **L1** (`l1_pooled.json`): pooled RR 2.30 (1.69-3.03), pass. Calibrated once (18 -> 6 mmHg).
- **L4 / L5** (`literature_checks_l4_l5.json`): revision-informed. L4 still 0 % cross-shift AKI vs ~50 % in cane
  cutters -> stated limitation.
- **R1a** (`r1_validation.json`): 99.29 % agreement with mimic-code KDIGO, pass. **R1b**: carry-forward beats our
  kinetic filter 24 h ahead (0.533 vs 0.556 mg/dL RMSE).
- **G3** (`g3_decision.json`): hybrid M leads by the pre-registered rule (beats B0 / B1 / B2). Plain LightGBM (B3) beats M
  on the mismatched world (0.064 vs 0.026 internal AUPRC); M wins under matched truth (0.22 vs 0.18). M on red catches
  26-43 % of AKI with 17-22 alerts per catch. Median lead 23 h: the pre-registered >= 24 h target is **missed**.
- **R3** (`r3_tawam.json`): slow-clock C-index 0.836 (0.776-0.889) vs baseline eGFR alone 0.834 (0.783-0.877):
  ranks as well as eGFR alone, not better (no serial eGFR in Tawam). KFRE not applicable there.
- **Demo personas** (`demo_numbers.json`): Kamala red at 43.5 % the day before her simulated AKI; what-if
  continue 48 % -> painkiller swap 25.5 % -> + ORS 1.5 % -> pauses <1 %.

---

## 5. Open decisions (waiting on the team)

1. **KDIGO boundary (R1a):** a rise of exactly 0.3 mg/dL can be read as 0.2999 in floating point and missed. A
   tolerance fix makes us clinically exact but drops agreement with mimic-code to 98.58 % (its own SQL misses exact-1.5x
   cases). Code is currently the pre-registered version. Affects 0 synthetic labels, only real lab input.
2. **Model choice:** keep M (pre-registered, 25 monotone features; recommended) or a post-hoc model with the last-lab
   ratio / M_full (needs an Amendment 3; 2025 / 2026 no longer untouched).
3. **Lead time:** state the 23 h result as "missed (one day ahead)" on the Reality Checks page?
4. Native-speaker review of the Hindi / Kannada / Telugu strings (`config/i18n/*.yaml`, marked "draft translation") and
   clinician sign-off of the two URGENT red-flag messages (`config/red_flags.yaml`, `clinical_wording: VERIFY`).

---

## 6. What is NOT done yet (next steps, in order)

### Part 5: done (18 Oct 2026)
Slow clock, KFRE, what-if levers, guardrails, sick-day guidance, `docs/CLINICAL_SAFETY.md` and R3. Details and
numbers in `PROGRESS.md` (Part 5).

### Part 6: services + trust layer (`src/vrikka/services/`, `src/vrikka/security/`, `src/vrikka/interop/`)
- One services layer enforcing role + consent + audit; Streamlit calls it in-process (FastAPI wrapper only if time).
- ABDM-style consent artefact checked on every read, with a revoke demo; role-based field filtering.
- Extend `security/audit.py` (HMAC hash chain already works) with signed checkpoints, verify, and a tamper demo.
- FHIR R4 export; DPDP mapping table; data-integrity gate (plausibility + replay rejection); Ed25519 device signing as
  one unit test only.
- Tests S10 (implausible feed rejected) and S11 (consent revoked); R4 = false red alerts on PMData (secondary line).

### Part 7: pages + full evaluation (`app/`)
- Pages: Doctor Triage (with "Order home kidney test" -> tasks table), Patient Twin (what-if + slow clock + sleep/steps),
  Patient / Family (pre-generated TTS in EN / HI / KN / TE), ASHA Tier-0 (Telugu; build the form from
  `config/red_flags.yaml` `capture_fields`), Trust Center, Time Machine, Evaluation / Reality Checks
  (calibration / held-out / revision-informed). No live Whisper in the hosted app. Text check-in uses
  `whatif/red_flags.parse_text` + brand recognition (rapidfuzz, "combiflam" -> ibuprofen + paracetamol, read-back).
- Red flags run before any risk (`whatif/red_flags.screen_then_risk`); display rules from `fastclock/display.py`.
- Evaluation extras: prevalence-shift table (already in the eval JSONs), ablations (with / without wearables, Tier 0 vs
  Tier 1), perfect vs noisy forecast, subgroups, tornado over the top 10 parameters (phi_drink in the top 3).
  Use the frozen Part 4 models and thresholds; do not retune on 2025 / 2026.
- Feature freeze, then Part 8.

### Part 8: submission
- README with every required item (team + college, title, problem + use case, tech stack + model details, video link,
  licence, architecture diagram PDF, presentation PDF) and numbers only from `reports/*.json`.
- `docs/DESIGN.md`, `docs/NUMBERS_CHECKED.md` (fact, number, URL, checked by, date). Slide numbers only from rows marked
  supported.
- Architecture diagram (mermaid -> PDF), slides (PPTX + PDF), video 20:00-20:15 unlisted YouTube.
- Deploy (Hugging Face Spaces Docker; fallback Streamlit Cloud).
- Make the repo **public**, test every link logged-out, and the team leader submits on Unstop.

---

## 7. Private planning files (NOT in the repo, on purpose)

The master plan, build plans, decision files (v1, v2, v4, v5), `HANDOFF_CONTEXT.md` and the draft `math-context.md` are
gitignored because the repo will be made public. Ask the team leader to share them directly. Their content that the code
depends on is already reflected in the registry, `reports/EVAL_PLAN.md`, `PROGRESS.md` and this file.
