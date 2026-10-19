# VrikkaTwin design summary

Public design notes for the Happiest Health Digital Twin Challenge 2026 entry of Team Monarch (Vellore Institute of
Technology). The architecture diagram is `deliverables/architecture.pdf`; the maths is in `docs/MATH_CONTEXT.md`; the
safety case in `docs/CLINICAL_SAFETY.md`; the data sources in `docs/DATA_SEARCH.md`; the evaluation plan in
`reports/EVAL_PLAN.md`; the build log, with every number tied to a report file, in `PROGRESS.md`.

## 1. Problem and use case

People with hypertension or chronic kidney disease (CKD) in India face two everyday threats to their kidneys:
heatwaves (sweat losses on top of diuretics) and sick days (fever, vomiting, diarrhoea, a painkiller bought at the
pharmacy). The "triple whammy" of an ACE inhibitor or ARB, a diuretic and an NSAID is common and avoidable. Kidney
injury in these episodes is usually mild and usually recovers, but it is silent: creatinine is rarely measured at
home, and repeated episodes are associated with faster long-term decline.

VrikkaTwin keeps a personal digital twin of a person's body water and kidney function, updated every morning from a
weight and a resting heart rate (a phone, a cheap band, or a weekly ASHA visit), and answers three questions:
1. **Fast clock:** how likely is kidney injury in the next 72 hours, and why?
2. **What if:** which safer choice (swap the painkiller, ORS, move work earlier, discuss a medicine pause) lowers it?
3. **Slow clock:** what range of long-term eGFR is likely, and how does a kidney injury this season shift it?

Users: the doctor (triage and a home kidney test order), the patient and family (plain language in English, Hindi,
Kannada and Telugu, with audio), the ASHA worker (a Tier-0 red-flag form), and the lab.

## 2. Architecture

```
weather (Open-Meteo, 7 cities)  --+
routine, symptoms, tablets, ORS --+--> exposure (ISO 7933 PHS sweat) --+
morning weight / resting HR / BP -------------------------------------+--> personal twin (UKF, 5 states)
labs (creatinine) ----------------------------------------------------+        |
                                                                                v
      red flags (run first) --> Monte-Carlo 72 h on the noisy forecast --> features --> hybrid model M (LightGBM,
                                                                                         25 monotone features)
                                                                                         -> calibrated risk, top-3
      what-if levers (same draws) <------------------------------------------------- twin       reasons, alert level
      slow clock (Bayesian eGFR slope, ranges) <-- stable labs
                    |
      services layer: role -> own record / consent artefact -> audit -> field filtering
                    |
      Streamlit pages (in-process)   ·   FastAPI wrapper   ·   FHIR R4 export
```

The **synthetic world** (`src/vrikka/simulator/`) is kept apart from the model: the twin, fast clock, slow clock,
what-if, services and API packages never import it (a test enforces this). The headline evaluation uses a
**mismatched** world whose truth equations differ from the twin's (pressure autoregulation instead of the twin's
protection model, hidden per-patient parameters, co-trimoxazole and muscle-breakdown causes the twin does not know).

## 3. Components

| Component | Module | What it does |
|---|---|---|
| Physiology engine | `physiology/` | CKD-EPI 2021, KFRE, KDIGO (one 08:00 creatinine per day), ISO 7933 PHS sweat, two-deficit volume model, drug effects with per-drug half-lives, autoregulation, mass-conserving creatinine kinetics, exertion |
| Personal twin | `twin/` | 5-state Unscented Kalman Filter (total and extracellular water deficit, creatinine, log sweat multiplier, dry weight); Monte-Carlo 72-h risk with the same KDIGO functions as the labels |
| Fast clock | `fastclock/` | 61 observed-only features at 09:00; baselines B0-B4; hybrid model M on 25 core features with monotone constraints; isotonic calibration; two-budget alerts with hysteresis and 72-h de-duplication; reasons from LightGBM contributions; the frozen models in `fastclock/frozen.py` |
| Slow clock | `slowclock/` | conjugate Bayesian eGFR slope (registry priors), Monte-Carlo ranges, fading applied-once AKI penalty, SGLT2i effect as an input, KFRE only where valid |
| What-if and safety | `whatif/` | red flags before any model; levers in a fixed order; ORS, paracetamol, potassium, heart-failure and co-trimoxazole guardrails; exclusions; sick-day guidance |
| Trust | `security/`, `interop/`, `services/`, `store/`, `api/` | roles, consent artefacts, signed audit checkpoints, integrity gate, encryption at rest, FHIR R4, DPDP mapping |
| App | `app/` | 8 Streamlit pages |

Every constant lives in `config/parameters.yaml` with its unit, range, provenance (CITED / VERIFY / ASSUMPTION) and
source. Clinical rules live in `config/guardrails.yaml`, `config/red_flags.yaml`, `config/integrity.yaml` and
`config/alert_policy.yaml`.

## 4. Key design decisions

- **Labels and twin read creatinine the same way:** one fasting 08:00 value per day, the same KDIGO code and the same
  baseline rule. Transient cross-shift rises are not labelled AKI.
- **Pre-registered evaluation** (`reports/EVAL_PLAN.md`, committed before any model and amended twice before any model
  was trained): headline on the mismatched world, held-out 2025 and 2026 seasons with separate test patients,
  patient-level bootstrap CIs, alert budgets, lead time, and the rule that decides which model leads (G3).
- **Honest reporting:** failures are shown as failures (L4, R1b, the 24-h lead-time target, a plain LightGBM beating
  the hybrid model on the mismatched world). Nothing is retuned on 2025 / 2026.
- **Ranges, not single numbers**, for the slow clock and every Monte-Carlo risk ("<1%", never "0%").
- **Safety first:** red flags override the model; medicine pauses come last and are always the clinician's decision.
- **Trust by construction:** one services layer enforces role, consent and audit for every read, from the app and from
  the API alike.

## 5. Tech stack

Python 3.12; NumPy, SciPy, pandas, PyArrow; filterpy (UKF); pythermalcomfort (ISO 7933 PHS); LightGBM, scikit-learn,
lifelines; kfre; Streamlit and Plotly (app); FastAPI and Uvicorn (API); cryptography (Fernet, Ed25519), PyJWT, bcrypt;
DuckDB (mimic-code KDIGO SQL for R1a); gTTS (pre-generated audio); rapidfuzz (brand recognition). Exact versions in
`requirements.lock`.

## 6. Limits

See `docs/CLINICAL_SAFETY.md` section 6. In short: synthetic validation only; creatinine lags filtration; the lead
time target was missed; a plain LightGBM beat the hybrid model on the mismatched world; heavy outdoor workers' transient
rises are under-represented; translations and two urgent messages await review; not a medical device.
