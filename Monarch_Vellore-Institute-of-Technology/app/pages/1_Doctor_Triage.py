"""Doctor Triage: patients ranked by level, with reasons, labs, KFRE where valid, and 'Order home kidney test'."""
from __future__ import annotations

import json

import streamlit as st
from components import charts
from components.api_client import require, services
from components.reports import report
from components.theme import badge, frame, lang, level_icon

from vrikka.config import load_yaml
from vrikka.i18n import t
from vrikka.security.rbac import AccessDenied
from vrikka.services import directory

frame("Doctor Triage", "🩺")
s = require("doctor")
sv = services()
L = lang()
meta = directory.panel_meta()
prev = report("fastclock_eval_mismatched").get("test_2025", {}).get("M_hybrid_core25", {}).get("day_level", {}).get(
    "prevalence")
bands = load_yaml("alert_policy")["levels"]

rows = sv.list_triage(s)
panel = [r for r in rows if r.get("risk_basis") == "model_M"]
personas = [r for r in rows if r.get("risk_basis") == "twin_simulation"]


def word(level: str) -> str:
    return f"{level_icon(level)} {t(f'level.{level}', L)}"


def reasons_text(r: dict) -> str:
    return "; ".join(t(k, L) for k in r.get("reasons", [])[:3])


kw = meta.get("kidney_weather")
if kw:
    with st.container(border=True):
        st.subheader(f"🌡️ Tomorrow's Kidney Weather ({kw['tomorrow']})")
        st.caption(f"Forecast: {kw['forecast']}. Levels: {kw['levels_basis']}, frozen model M, all held-out test "
                   "patients (synthetic).")
        st.dataframe([{"city": c, "forecast max tomorrow (°C)": v["forecast_tmax_tomorrow_c"],
                       "what ERA5 later recorded (°C)": v["archived_tmax_tomorrow_c"], "patients": v["patients"],
                       word("green"): v["green"], word("amber"): v["amber"], word("red"): v["red"]}
                      for c, v in sorted(kw["cities"].items(), key=lambda x: -x[1]["red"])],
                     hide_index=True, width="stretch")
        st.markdown(f"**Suggested home kidney tests today** ({kw['suggested_rule']}; showing "
                    f"{len(kw['suggested_tests_today'])} of {sum(v['red'] for v in kw['cities'].values())})")
        st.dataframe([{"patient": r["patient_id"], "city": r["city"], "72-h risk": r["risk_text"],
                       "main reason": t(r["top_reason"], L) if r["top_reason"] else ""}
                      for r in kw["suggested_tests_today"]], hide_index=True, width="stretch", height=250)

tab1, tab2 = st.tabs([f"Synthetic panel scored by model M ({len(panel)})", f"Fictional personas ({len(personas)})"])
with tab1:
    if meta:
        st.caption(f"{meta['source']}. {meta['model']}. Demo date **{meta['demo_date']}**: "
                   f"{meta['patients_in_red_state_that_day']} of {meta['eligible_patients_that_day']} test patients "
                   f"were red and {meta['patients_in_amber_state_that_day']} amber; the panel shows the red ones, the "
                   "highest ambers and a random sample of greens.")
        st.dataframe([{
            "level": word(r["level"]), "patient": r["patient_id"], "age": r["age"], "sex": "F" if r["female"] else "M",
            "city": r["city"], "72-h risk": r["risk_text"],
            "x average day": (f"{r['risk'] / prev:.0f}x" if prev else ""), "top reasons": reasons_text(r),
            "eGFR (baseline)": r["egfr_baseline"], "tier": r["tier"]} for r in panel],
            hide_index=True, width="stretch")
    else:
        st.warning("The triage panel report is missing: run `scripts/make_triage_panel.py`.")
with tab2:
    st.caption("Personas are fictional. Their risk is the twin's 72-hour simulation (share of Monte-Carlo runs meeting "
               f"the KDIGO rule) with display bands {100 * bands['green']['max_prob']:.0f} % / "
               f"{100 * bands['amber']['max_prob']:.0f} %; open one in Patient Twin for the what-if levers.")
    st.dataframe([{"level": word(r["level"]), "persona": r.get("name", r["patient_id"]), "label": r["label"],
                   "72-h twin risk": r["risk_text"], "drivers today": reasons_text(r)} for r in personas],
                 hide_index=True, width="stretch")

st.divider()
ids = [r["patient_id"] for r in rows]
names = {r["patient_id"]: f"{r.get('name') or r['patient_id']} ({r['patient_id']})" for r in rows}
pick = st.selectbox("Open a patient", ids, format_func=lambda i: names[i])
try:
    rec = sv.read_patient(s, pick)
except AccessDenied as e:
    st.error(f"Access denied: {e.reason} (the attempt is in the audit log).")
    st.stop()

c1, c2 = st.columns([2, 3])
with c1:
    st.markdown(f"### {rec.get('name', pick)}")
    st.markdown(badge(rec["level"], L), unsafe_allow_html=True)
    st.markdown(f"<div class='vt-hero'>{rec['risk_text']}</div><div class='vt-small'>72-hour kidney-injury risk "
                f"({'hybrid model M, calibrated' if rec['risk_basis'] == 'model_M' else 'twin simulation'})</div>",
                unsafe_allow_html=True)
    st.markdown(f"{rec['age']} y, {'female' if rec['female'] else 'male'}, {rec['city']} · medicines: "
                f"{', '.join(rec.get('generics', [])) or 'none'}")
    st.markdown("**Why (top reasons)**")
    for k in rec.get("reasons", [])[:3]:
        st.markdown(f"- {t(k, L)}")
    st.markdown("**Action:** " + t("action." + rec["level"], L))
    lab = rec.get("last_lab")
    if lab:
        tag = f" · ⚠️ {t(lab['tag_key'], L)}" if lab.get("tag_key") else ""
        st.markdown(f"**Last lab:** creatinine {lab['creatinine_mg_dl']} mg/dL, eGFR {lab['egfr']}{tag}")
    k = rec.get("kfre") or {}
    if k.get("valid"):
        st.markdown(f"**{t('kfre.label', L)}:** 2 y {100 * k['risk_2y']:.1f} %, 5 y {100 * k['risk_5y']:.1f} %"
                    + (" · referral prompt" if k.get("referral_prompt") else ""))
    elif k:
        st.caption(t(k["reason_key"], L))
    b1, b2 = st.columns(2)
    if b1.button("🧪 Order home kidney test", type="primary"):
        tid = sv.order_kidney_test(s, pick, reason=f"{rec['level']} alert")
        st.success(f"Task {tid} created for the lab (see Lab Tasks). Logged in the audit trail.")
    b2.download_button("⬇️ FHIR R4 export", json.dumps(sv.export_fhir(s, pick), indent=1),
                       file_name=f"{pick}_fhir_bundle.json", mime="application/fhir+json")
with c2:
    if rec["risk_basis"] == "model_M":
        tr = rec["trajectory"]
        st.plotly_chart(charts.risk_trajectory(
            tr["dates"], tr["risk"], tr["level"], "Calibrated 72-h risk, last 14 days (model M)", "risk (%)",
            bands={"red threshold": meta["red_threshold"], "amber threshold": meta["amber_threshold"]}),
            width="stretch", theme="streamlit")
        st.dataframe({"date": tr["dates"], "steps": tr["steps"], "sleep (h)": tr["sleep_h"],
                      "weight vs usual (kg)": tr["wt_vs_dry_kg"], "resting HR vs usual": tr["hr_delta_bpm"]},
                     hide_index=True, width="stretch", height=220)
        sc = rec.get("slow_clock", {})
        if sc:
            st.markdown(f"**Slow clock** ({sc['stable_labs_used']} stable labs, prior: {sc['prior_group']}): "
                        "eGFR in 10 "
                        f"years {sc['egfr_10y_range'][0]}-{sc['egfr_10y_range'][2]} (median "
                        f"{sc['egfr_10y_range'][1]}); below 30: {sc['years_to']['g4']}.")
        with st.expander("Reveal the simulation truth (never seen by the model)"):
            th = rec.get("truth_hidden", {})
            st.write("Simulated kidney injury within 72 h: **"
                     + ("yes" if th.get("aki_onset_within_72h") else "no") + "**. " + th.get("note", ""))
            if meta:
                st.caption(f"Of the {meta['panel']['red']} red patients in this panel, "
                           f"{meta['panel_red_with_aki_within_72h']} had a simulated injury within 72 h: a red alert "
                           "means 'test and review', not a diagnosis (see the PPV on the Evaluation page).")
    else:
        st.plotly_chart(charts.risk_trajectory(
            rec["dates"], rec["risk_by_day"], rec["levels_by_day"], "Twin 72-h simulated risk by day (demo replay)",
            "risk (%)", bands={"red band": bands["amber"]["max_prob"], "amber band": bands["green"]["max_prob"]}),
            width="stretch", theme="streamlit")
        st.caption("Open **Patient Twin** for what-if levers and slow-clock ranges.")
    if rec.get("tasks"):
        st.markdown("**Kidney-test tasks**")
        st.dataframe(rec["tasks"], hide_index=True, width="stretch")
