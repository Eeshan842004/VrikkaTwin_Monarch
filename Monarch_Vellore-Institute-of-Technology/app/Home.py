"""VrikkaTwin home page: what it is, who each page is for, and the honest headline numbers (from reports/)."""
from __future__ import annotations

import streamlit as st
from components.reports import report
from components.theme import badge, frame, lang

from vrikka.config import load_yaml, param
from vrikka.fastclock.features import CORE

frame("VrikkaTwin: a kidney digital twin for heatwaves and sick days")
L = lang()
DRAWS = int(param("mc_draws_ui"))
BAND = f"{100 * param('slow_band_low_q'):.0f}-{100 * param('slow_band_high_q'):.0f} %"
CALL = load_yaml("red_flags")["flags"]["heatstroke_emergency"]["call"]

st.markdown(
    "VrikkaTwin estimates the risk of **acute kidney injury (usually mild, usually recovers)** over the next 72 hours "
    "for people with hypertension or chronic kidney disease, during heatwaves and sick days (fever, vomiting, "
    "diarrhoea, a new painkiller). It also shows **long-term eGFR ranges** and **what-if** comparisons of safer "
    "choices. Every number below is read from `reports/*.json`; every person is synthetic or fictional.")

c1, c2, c3 = st.columns(3)
with c1:
    st.markdown("#### ⚡ Fast clock (hours to days)")
    st.markdown("A personal **twin** (Unscented Kalman Filter over body water and creatinine) learns from the morning "
                f"weight and resting heart rate, simulates the next 72 hours {DRAWS} times on the weather "
                "forecast, and a "
                f"**hybrid model M** ({len(CORE)} monotone features) turns that into a calibrated risk with its "
                "top-3 reasons.")
with c2:
    st.markdown("#### 🐢 Slow clock (years)")
    st.markdown(f"A **Bayesian eGFR slope** (registry priors by diabetes / albuminuria) projects {BAND} ranges, with "
                "the AKI penalty applied once, fading, and stated as *associated with*. KFRE only where valid.")
with c3:
    st.markdown("#### 🛡️ Safety and trust")
    st.markdown(f"**Red flags run before any risk** (heatstroke: call {CALL}). Guardrails on ORS, paracetamol, "
                "potassium and heart failure. Every read checks a signed consent artefact and lands in a "
                "hash-chained, signed audit log.")

g3 = report("g3_decision")
r1 = report("r1_validation")
r3 = report("r3_tawam")
r4 = report("r4_pmdata")
st.divider()
st.subheader("Headline results (honest version)")
if g3:
    m = g3["auprc"]["M_hybrid_core25"]
    b3 = g3["auprc"]["B3_lightgbm_raw"]
    lead = g3["lead_time_target_A1_3"]
    cols = st.columns(4)
    cols[0].metric("G3 (pre-registered rule)", "M leads" if all(g3["M_beats"].values()) else "B4 leads",
                   help="M beats the last-lab, heat-index and points baselines on mismatched AUPRC "
                        "(2024 internal-test patients)")
    prev = report("fastclock_eval_mismatched")["internal_test_2024"]["M_hybrid_core25"]["day_level"]["prevalence"]
    cols[1].metric("M internal-test AUPRC", f"{m['value']:.4f}", help=f"95% CI {m['ci95'][0]}-{m['ci95'][1]}; "
                   f"positive-day prevalence {100 * prev:.2f} %")
    cols[2].metric("Plain LightGBM (B3) AUPRC", f"{b3['value']:.4f}", delta="beats M on the mismatched world",
                   delta_color="off")
    cols[3].metric("Median lead time (target >= 24 h)", f"{lead['median_h_trigger_ge_24h']:.0f} h",
                   delta="target missed" if not lead["met"] else "met", delta_color="inverse")
cols = st.columns(4)
if r1:
    cols[0].metric("R1a labelling vs mimic-code KDIGO", f"{r1['R1a']['agreement_pct']}%",
                   help="real MIMIC-IV demo data")
    p = r1["R1b"]["pooled"]["rmse_mg_dl"]
    cols[1].metric("R1b 24-h creatinine RMSE", f"{p['kinetic_filter']:.3f} mg/dL",
                   delta=f"carry-forward {p['carry_forward']:.3f} wins", delta_color="off")
if r3:
    cols[2].metric("R3 slow-clock C-index (Tawam)", f"{r3['c_index_slow_clock_years_to_60']:.3f}",
                   delta=f"baseline eGFR alone {r3['c_index_baseline_egfr_alone']:.3f}", delta_color="off")
if r4:
    cols[3].metric("R4 false red alerts (PMData)", f"{r4['red_notifications_per_100_patient_days']:.1f} per 100 days",
                   help=f"{r4['people']} healthy people, {r4['patient_days']} person-days")

st.divider()
st.subheader("Who each page is for")
pages = [
    ("1 Doctor Triage", "doctor", "Ranked patients, reasons, order a home kidney test"),
    ("2 Patient Twin", "doctor / patient", "Twin state, what-if levers, slow-clock ranges"),
    ("3 Patient and Family", "patient / family", "Plain language in EN / HI / KN / TE with audio"),
    ("4 ASHA Field", "ASHA worker", "Tier-0 red-flag form (Telugu by default) and text check-in"),
    ("5 Lab Tasks", "lab", "Home kidney test orders and results"),
    ("6 Trust Center", "everyone", "Consent, audit log, tamper demo, data-integrity gate, FHIR, DPDP"),
    ("7 Time Machine", "everyone", "Replay a persona's heatwave day by day"),
    ("8 Evaluation", "everyone", "Reality checks: calibration, held-out, revision-informed"),
]
for name, who, what in pages:
    st.markdown(f"- **{name}** ({who}): {what}")
st.caption("Alert levels always show an icon, a word and a colour: "
           + " ".join(badge(lv, L) for lv in ("green", "amber", "red", "purple")), unsafe_allow_html=True)
