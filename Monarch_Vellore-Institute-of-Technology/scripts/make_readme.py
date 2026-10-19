"""Write README.md from a template whose every number is read from reports/*.json (working rule: no hand-typed numbers).

    python scripts/make_readme.py

External facts come only from rows marked "supported" in docs/NUMBERS_CHECKED.md. Re-run after any report changes.
"""
from __future__ import annotations

import json
import sys

from vrikka.config import PROJECT_ROOT, REPORTS_DIR, load_yaml, param
from vrikka.fastclock.features import CORE, FULL

VIDEO_URL = "VIDEO LINK: add the unlisted YouTube URL here after upload"


def R(name: str) -> dict:
    p = REPORTS_DIR / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def main() -> int:
    ev, g3, demo = R("fastclock_eval_mismatched"), R("g3_decision"), R("demo_numbers")
    evm, r1, r3, r4 = R("fastclock_eval_matched"), R("r1_validation"), R("r3_tawam"), R("r4_pmdata")
    l1, cal, l45, coh, extra = R("l1_pooled"), R("calibration_checks"), R("literature_checks_l4_l5"), \
        R("cohort_summary"), R("evaluation_extras")
    it = ev["internal_test_2024"]
    m = it["M_hybrid_core25"]
    k = demo["scenarios"]["S1_riya"]
    w = list(k["whatif_72h_risk"].values())
    pd_ = g3["paired_difference_M_minus"]
    lead = g3["lead_time_target_A1_3"]
    ops = {s: ev[s]["M_hybrid_core25"]["alerts"] for s in ("internal_test_2024", "test_2025", "test_2026")}
    pol = load_yaml("alert_policy")
    rb = r1["R1b"]["pooled"]["rmse_mg_dl"]
    ss = cal["sweat_sensitivity"]
    seasons = coh["seasons"]

    def auprc_row(key: str, name: str) -> str:
        cells = [f"{ev[s][key]['day_level']['auprc']:.4f}" for s in ("internal_test_2024", "test_2025", "test_2026")]
        return f"| {name} | " + " | ".join(cells) + " |"

    rob = extra.get("robustness", {})
    rob_lines = []
    names = {"headline_noisy_forecast": "Headline (noisy forecast)", "perfect_forecast": "Perfect forecast",
             "no_band": "No wearable band", "tier0_only": "Everyone Tier 0 (weekly ASHA weight)",
             "drop30": "30 % of band days missing", "drop50": "50 % of band days missing", "noise2x": "Sensor noise x2"}
    for key, nm in names.items():
        if key in rob:
            v = rob[key]
            rob_lines.append(f"| {nm} | {v['auprc']} | {100 * v['sensitivity_red']:.0f} % | "
                             f"{v['red_per_100_patient_days']} | {v['median_lead_h']} |")
    tor = extra.get("tornado", {})
    rep = extra.get("reproduction", {})
    rep_ok = all(mm["reproduced"] for y in rep.values() for mm in y["models"].values()) if rep else None

    text = f"""# VrikkaTwin: a kidney digital twin for heatwaves and sick days

**Team Monarch, Vellore Institute of Technology** · Happiest Health Digital Twin Challenge 2026
Team: Harshita Kumar and Eeshan Gupta.

VrikkaTwin warns of **acute kidney injury (usually mild, usually recovers)** up to **72 hours ahead** for people with
hypertension or chronic kidney disease during heatwaves and sick days, shows the safer choices that lower that risk,
and projects long-term kidney function as honest ranges. It is a research prototype tested on synthetic patients and
open datasets: **not a medical device**; every person shown is synthetic or fictional.

| Deliverable | Where |
|---|---|
| Video (demo walkthrough) | {VIDEO_URL} (script: [`docs/VIDEO_SCRIPT.md`](docs/VIDEO_SCRIPT.md)) |
| Architecture diagram (PDF) | [`deliverables/architecture.pdf`](deliverables/architecture.pdf) |
| One-day data flow (PDF) · app screenshots | [`deliverables/daily_flow.pdf`](deliverables/daily_flow.pdf) · [`deliverables/screenshots/`](deliverables/screenshots/) |
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
2. **Fast clock.** Every morning the twin simulates the next 72 hours {int(param('mc_draws_ui'))} times on a noisy
   forecast and applies the same KDIGO rule (one 08:00 creatinine a day) used for the labels. A hybrid model M
   (LightGBM, {len(CORE)} monotone core features out of {len(FULL)}) turns this into a calibrated risk with its top-3
   reasons. Alerts are budgeted in advance: red at most {pol['red_budget_per_100_patient_days']} and amber + red at most
   {pol['alert_budget_per_100_patient_days']} notifications per 100 patient-days.
3. **What-if.** Levers in a fixed order (painkiller swap, then ORS and work hours, then medicine pauses last, which the
   clinician decides), all simulated with the same random draws.
4. **Slow clock.** A Bayesian eGFR slope with registry priors; {100 * param('slow_band_low_q'):.0f}-{100 * param('slow_band_high_q'):.0f} % ranges only; the AKI penalty
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

Enriched high-risk heat-season cohort: {coh['n_train_patients']:,} training patients (2024 season) and
{coh['n_test_patients']:,} separate test patients (2025 and 2026 seasons); {seasons['2024']['mismatched']['aki_episodes']}
/ {seasons['2025']['mismatched']['aki_episodes']} / {seasons['2026']['mismatched']['aki_episodes']} kidney-injury episodes
(mismatched world); positive-day prevalence {100 * m['day_level']['prevalence']:.2f} %.

**AUPRC on the mismatched world** (2024 internal test / 2025 held-out / 2026 held-out):

| Model | 2024 | 2025 | 2026 |
|---|---|---|---|
{auprc_row('B0_last_lab_logistic', 'B0 last lab')}
{auprc_row('B1_heat_index_rule', 'B1 heat-index rule')}
{auprc_row('B2_triple_heat_egfr_points', 'B2 points score')}
{auprc_row('B3_lightgbm_raw', 'B3 plain LightGBM')}
{auprc_row('B4_twin_physics_risk', 'B4 twin physics only')}
{auprc_row('M_hybrid_core25', '**M hybrid (lead)**')}
{auprc_row('M_full_sensitivity', 'M_full (sensitivity)')}

- **Pre-registered rule (G3): M leads**: it beats B0 / B1 / B2 (paired differences
  {pd_['B0_last_lab_logistic']['point']:+.4f} / {pd_['B1_heat_index_rule']['point']:+.4f} /
  {pd_['B2_triple_heat_egfr_points']['point']:+.4f}, all CIs exclude 0).
- **A plain LightGBM (B3) beats M on the mismatched world** (paired difference {pd_['B3_lightgbm_raw']['point']:+.4f},
  CI {pd_['B3_lightgbm_raw']['ci95'][0]:+.4f} to {pd_['B3_lightgbm_raw']['ci95'][1]:+.4f}). M wins on the matched world
  ({evm['internal_test_2024']['M_hybrid_core25']['day_level']['auprc']:.3f} vs
  {evm['internal_test_2024']['B3_lightgbm_raw']['day_level']['auprc']:.3f}) and is the model the what-if runs on.
- **Operational (M, red):** catches {100 * ops['internal_test_2024']['sensitivity_red']:.0f} /
  {100 * ops['test_2025']['sensitivity_red']:.0f} / {100 * ops['test_2026']['sensitivity_red']:.0f} % of injury episodes
  with {ops['internal_test_2024']['alerts_per_aki_caught_red']:.1f} / {ops['test_2025']['alerts_per_aki_caught_red']:.1f} /
  {ops['test_2026']['alerts_per_aki_caught_red']:.1f} red alerts per injury caught (2024 / 2025 / 2026).
- **Lead time:** median {lead['median_h_trigger_ge_24h']:.0f} h. **The pre-registered target of at least 24 h was
  missed** (one prediction a day at 09:00 against an 08:00 onset makes "the day before" read just under 24 h).
- **Riya (fictional persona):** red at {100 * k['risk_by_day'][k['summary']['first_red_day']]:.1f} % the morning before
  her simulated injury; what-if: continue {100 * w[0]:.1f} % -> painkiller swap {100 * w[1]:.1f} % -> + ORS
  {100 * w[2]:.1f} % -> + pauses <1 %; same tablets with CYP2C9 *3/*3 {100 * w[4]:.1f} %.

**Reality checks on real data and literature**

| Check | Category | Result |
|---|---|---|
| R1a labelling vs official mimic-code KDIGO (MIMIC-IV demo) | held-out | {r1['R1a']['agreement_pct']} % agreement: pass |
| R1b 24-h creatinine forecast (MIMIC + eICU demos) | held-out | kinetic filter {rb['kinetic_filter']:.3f} vs carry-forward {rb['carry_forward']:.3f} mg/dL RMSE: **carry-forward wins** |
| R3 slow-clock ranking (Tawam, {r3['patients']} patients) | held-out | C-index {r3['c_index_slow_clock_years_to_60']:.3f} vs baseline eGFR alone {r3['c_index_baseline_egfr_alone']:.3f}: as good, not better |
| R4 false alarms on healthy people (PMData, {r4['people']} people) | held-out | {r4['red_notifications_per_100_patient_days']} red notifications per 100 person-days |
| L1 triple vs double therapy | calibration | RR {l1['pooled']['rr']} ({l1['pooled']['ci95'][0]}-{l1['pooled']['ci95'][1]}), band {l1['pass_band'][0]}-{l1['pass_band'][1]}: pass |
| Heat share of injuries | calibration | about {100 * ss['x0.7']['haf']:.0f}-{100 * cal['haf_matched_regime']['haf']:.0f} % depending on assumptions (central {100 * cal['haf']['all']['haf']:.1f} %) |
| L4 cross-shift AKI in a heavy outdoor worker | revision-informed | {l45['L4']['twin_engine']['share_end_of_shift_aki_pct']:.0f} % vs about half of cane cutters: **stated limitation** |
"""
    if rob_lines:
        text += f"""
**Robustness** ({rob.get('season')} held-out season, the same {rob.get('patients')} test patients in every row; frozen
model, nothing retuned):

| Variant | AUPRC | Red sensitivity | Red per 100 patient-days | Median lead (h) |
|---|---|---|---|---|
""" + "\n".join(rob_lines) + "\n"
    if tor:
        text += (f"\nSensitivity: {tor['parameters_screened']} registry assumptions screened on Riya's 72-h risk; "
                 f"the drinking fraction ranks {tor['phi_drink_rank']}. ")
    if rep_ok is not None:
        text += ("Re-generating the cohort and features on a second machine reproduces the reported held-out AUPRC: "
                 + ("yes." if rep_ok else "no (see reports/evaluation_extras.json).") + "\n")
    text += """
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
"""
    (PROJECT_ROOT / "README.md").write_text(text, encoding="utf-8")
    print("README.md written,", len(text.splitlines()), "lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
