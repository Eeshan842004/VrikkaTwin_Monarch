"""Evaluation / Reality Checks (EVAL_PLAN with Amendments 1-2): every check in its category - calibration (may inform
parameters), held-out (never used for tuning), revision-informed (shown next to its v1 failure) - with failures shown
as failures. Every number is read from reports/*.json."""
from __future__ import annotations

import streamlit as st
from components import charts
from components.reports import ci_text, report
from components.theme import frame

from vrikka.config import load_yaml
from vrikka.fastclock.features import CORE

frame("Evaluation: reality checks", "📊")
POL = load_yaml("alert_policy")

g3 = report("g3_decision")
ev = report("fastclock_eval_mismatched")
evm = report("fastclock_eval_matched")
r1, r3, r4 = report("r1_validation"), report("r3_tawam"), report("r4_pmdata")
cal, l1p, l45 = report("calibration_checks"), report("l1_pooled"), report("literature_checks_l4_l5")
r2, noise, extra = report("r2_overlay"), report("pmdata_noise"), report("evaluation_extras")
MODELS = {"B0_last_lab_logistic": "B0 last lab", "B1_heat_index_rule": "B1 heat-index rule",
          "B2_triple_heat_egfr_points": "B2 points", "B3_lightgbm_raw": "B3 plain LightGBM",
          "B4_twin_physics_risk": "B4 twin physics", "M_hybrid_core25": "M hybrid (lead)",
          "M_full_sensitivity": "M_full (sensitivity)"}
SETS = {"internal_test_2024": "2024 internal test", "test_2025": "2025 held-out", "test_2026": "2026 held-out"}


def verdict(ok: bool | None, yes: str = "PASS", no: str = "MISSED") -> str:
    return "✅ " + yes if ok else ("❌ " + no if ok is not None else "ℹ️ reported")


st.markdown("**Categories (Amendment 2 A2.2).** *Calibration* checks may inform parameters. *Held-out* checks were "
            "never used for tuning. *Revision-informed* checks motivated the engine revision and are always shown "
            "next to their first failure. A held-out failure is shown as a failure; nothing was retuned.")

# ------------------------------------------------------------------------------------------- fast clock
st.header("1 · Fast clock on the synthetic world (headline: mismatched simulator)")
if ev:
    tbl = []
    for k, name in MODELS.items():
        row = {"model": name}
        for sk, sname in SETS.items():
            d = ev[sk][k]["day_level"]
            row[sname] = f"{d['auprc']:.4f} ({ci_text(d['auprc_ci95'])})"
        tbl.append(row)
    st.dataframe(tbl, hide_index=True, width="stretch")
    it = ev["internal_test_2024"]
    vals = [it[k]["day_level"]["auprc"] for k in MODELS]
    st.plotly_chart(charts.bars(list(MODELS.values()), vals, "AUPRC, 2024 internal-test patients (95 % CI)",
                                "AUPRC", highlight="M hybrid (lead)",
                                errors=[tuple(it[k]["day_level"]["auprc_ci95"]) for k in MODELS],
                                text=[f"{v:.4f}" for v in vals]), width="stretch", theme="streamlit")
    prev = it["M_hybrid_core25"]["day_level"]["prevalence"]
    st.caption(f"Positive-day prevalence {100 * prev:.2f} % (enriched high-risk heat-season cohort), so AUPRC values "
               "are small in absolute terms; compare them with the prevalence and with each other.")
if g3:
    pd_ = g3["paired_difference_M_minus"]
    st.markdown(f"**G3 (pre-registered rule A1.4): {verdict(all(g3['M_beats'].values()), 'M leads', 'B4 leads')}.** "
                "M beats B0 / B1 / B2 with paired AUPRC differences " + ", ".join(
                    f"{MODELS[b].split()[0]} {pd_[b]['point']:+.4f} ({ci_text(pd_[b]['ci95'])})"
                    for b in ("B0_last_lab_logistic", "B1_heat_index_rule", "B2_triple_heat_egfr_points")) + ".")
    b3 = pd_["B3_lightgbm_raw"]
    st.markdown(f"❌ **M does not beat a plain LightGBM (B3) on the mismatched world**: paired difference "
                f"{b3['point']:+.4f} ({ci_text(b3['ci95'])}). Most of B3's edge comes from the last-lab creatinine "
                "ratio, which M's " + str(len(CORE)) + " monotone core features leave out. Per EVAL_PLAN 15.5 we "
                "say so; M is kept "
                "because it was pre-registered and because the twin behind it is what makes the what-if possible.")
if evm:
    st.markdown("**Matched world (optimistic ceiling):** " + ", ".join(
        f"{MODELS[k]} {evm['internal_test_2024'][k]['day_level']['auprc']:.3f}"
        for k in ("B3_lightgbm_raw", "B4_twin_physics_risk", "M_hybrid_core25")) + " (2024 internal test).")

st.subheader(f"Operational numbers for M (frozen thresholds: red <= {POL['red_budget_per_100_patient_days']}, "
             f"amber + red <= {POL['alert_budget_per_100_patient_days']} notifications per 100 patient-days)")
if ev:
    rows = []
    for sk, sname in SETS.items():
        a, d = ev[sk]["M_hybrid_core25"]["alerts"], ev[sk]["M_hybrid_core25"]["day_level"]
        rows.append({"set": sname, "red sensitivity": f"{100 * a['sensitivity_red']:.0f} % "
                     f"({ci_text(a['sensitivity_red_ci95'], 0, 100)})",
                     "red alerts per AKI caught": f"{a['alerts_per_aki_caught_red']:.1f}",
                     "red per 100 pt-days": f"{a['red_per_100_patient_days']:.2f}",
                     "amber-or-red sensitivity": f"{100 * a['sensitivity_amber_or_red']:.0f} %",
                     "red-day PPV (ceiling)": f"{100 * a['ppv_red_day']:.1f} % "
                                              f"({100 * a['ppv_ceiling_red_day']:.0f} %)",
                     "PPV at 1/10 | 1/50 prevalence": f"{100 * a['ppv_red_day_at_1_10_prevalence']:.2f} % | "
                                                      f"{100 * a['ppv_red_day_at_1_50_prevalence']:.2f} %",
                     "calibration slope": d["calibration_slope"], "within-patient AUROC": d["within_patient_auroc"]})
    st.dataframe(rows, hide_index=True, width="stretch")
    st.caption("A red alert means 'test creatinine and review painkillers', not a diagnosis: the PPV is low because "
               "kidney injury is rare on any single day, and it falls further at real-world prevalence "
               "(prevalence-shift rows, Amendment 1 A1.5).")

st.subheader("Lead time (A1.3)")
if g3:
    lt = g3["lead_time_target_A1_3"]
    lead = ev["internal_test_2024"]["M_hybrid_core25"]["alerts"]["lead_time"]
    st.markdown(f"{verdict(lt['met'])} Target: median >= 24 h on episodes whose sick-day trigger began >= 24 h "
                f"before onset. Result: **{lt['median_h_trigger_ge_24h']:.0f} h**. {lead['note']}. "
                f"{lead['pct_caught_ge_24h_ahead']:.0f} % of caught episodes were already red two or more "
                "mornings ahead.")
    st.dataframe([{"trigger-to-onset gap": k.replace("_", " "), **v} for k, v in lead["by_trigger_gap"].items()],
                 hide_index=True, width="stretch")
    age = [ev[s].get("subgroup_age_75_plus_M") for s in ("test_2025", "test_2026")]
    if all(age):
        st.caption("Age >= 75 (M): AUPRC " + " / ".join(f"{a['auprc']:.3f}" for a in age) + ", red sensitivity "
                   + " / ".join(f"{100 * a['sensitivity_red']:.0f} %" for a in age)
                   + f" (2025 / 2026). {age[0]['note']}.")

# ------------------------------------------------------------------------------------------- held-out real data
st.header("2 · Held-out checks on real data (never used for tuning)")
c = st.columns(2)
with c[0]:
    if r1:
        a = r1["R1a"]
        st.markdown(f"**R1a, labelling vs official mimic-code KDIGO** {verdict(a['pass'])}: {a['agreement_pct']} % "
                    f"agreement on {a['values_compared']} values, {a['stays']} ICU stays (MIMIC-IV demo; threshold "
                    f"{a['pass_threshold_pct']} %). The disagreements are rises of exactly 0.3 mg/dL that floating "
                    "point reads as 0.2999 (open team decision).")
        b = r1["R1b"]["pooled"]
        st.markdown(f"**R1b, 24-h creatinine forecast** {verdict(b['kinetic_beats_carry_forward'])}: RMSE kinetic "
                    f"filter {b['rmse_mg_dl']['kinetic_filter']:.3f}, "
                    f"carry-forward {b['rmse_mg_dl']['carry_forward']:.3f}"
                    f", linear trend {b['rmse_mg_dl']['linear_trend']:.3f} mg/dL ({b['pairs']} pairs, {b['stays']} "
                    f"stays). Carry-forward wins (difference CI {ci_text(b['kinetic_minus_best_simple_ci95'])}).")
    if r3:
        st.markdown(f"**R3, slow-clock ranking (Tawam, {r3['patients']} patients, {r3['events_eGFR_below_60']} "
                    f"reached eGFR < 60)** ℹ️: C-index {r3['c_index_slow_clock_years_to_60']:.3f} "
                    f"({ci_text(r3['c_index_slow_clock_ci95'], 3)}) vs baseline eGFR alone "
                    f"{r3['c_index_baseline_egfr_alone']:.3f} ({ci_text(r3['c_index_baseline_egfr_ci95'], 3)}); "
                    f"difference CI {ci_text(r3['paired_difference_ci95'], 3)}: as good as eGFR alone, not better. "
                    f"KFRE: {r3['kfre']['note']}.")
with c[1]:
    if r4:
        st.markdown(f"**R4, false alarms on healthy real people (PMData)** "
                    f"{verdict(r4['red_notifications_per_100_patient_days'] == 0, 'target ~0 met')}: "
                    f"{r4['red_notifications_per_100_patient_days']} red and "
                    f"{r4['amber_plus_red_notifications_per_100_patient_days']} amber-or-red notifications per 100 "
                    f"person-days ({r4['people']} people, {r4['patient_days']} person-days). Caveats: {r4['caveats']}")
    if r2:
        st.markdown(f"**R2, lab plausibility vs UCI CKD** ℹ️ ({r2['claim']}; origin: {r2['uci_origin']})")
        st.dataframe([{"group": g, "lab": lab, "synthetic median": v["synthetic"]["median"],
                       "UCI median": v["uci"]["median"]} for g, labs in r2["groups"].items()
                      for lab, v in labs.items()], hide_index=True, width="stretch", height=220)

# ------------------------------------------------------------------------------------------- calibration
st.header("3 · Calibration checks (may inform parameters)")
if l1p:
    p = l1p["pooled"]
    st.markdown(f"**L1, triple whammy vs double therapy** {verdict(p['pass'])}: pooled RR {p['rr']} "
                f"({ci_text(p['ci95'], 2)}), band {l1p['pass_band'][0]}-{l1p['pass_band'][1]} (Lapi 2013). "
                f"{l1p['constant_calibrated_once']}.")
if cal:
    h = cal["haf"]["all"]
    ss = cal["sweat_sensitivity"]
    lo = min(ss["x0.7"]["haf"], h["haf"])
    hi = max(ss["x1.3"]["haf"], cal["haf_matched_regime"]["haf"])
    st.markdown(f"**Heat share (heat-attributable fraction)**: about **{100 * lo:.0f}-{100 * hi:.0f} %** depending on "
                f"assumptions; central {100 * h['haf']:.1f} % ({ci_text(h['haf_ci95'], 1, 100)} %) with air "
                f"capped at {cal['cap_c']:.0f} °C. Sweat x0.7 / x1.3: {100 * ss['x0.7']['haf']:.1f} % / "
                f"{100 * ss['x1.3']['haf']:.1f} %; matched truth {100 * cal['haf_matched_regime']['haf']:.1f} %.")
    occ = cal.get("haf_by_occupation", {})
    st.dataframe([{"occupation": k, "patients": v["patients"], "episodes": v["episodes_actual"],
                   "heat share": f"{100 * v['haf']:.1f} % ({ci_text(v['haf_ci95'], 1, 100)})"} for k, v in occ.items()],
                 hide_index=True, width="stretch")
    l2 = cal["L2"]
    st.markdown(f"**L2, events vs temperature** ℹ️: {l2['pct_change_per_degC']} % per °C, direction "
                f"{'correct' if l2['direction_ok'] else 'wrong'}; {l2['reference']}.")
if noise:
    st.markdown(f"**Resting-HR noise from PMData** ℹ️: sigma_hr = {noise['sigma_hr_bpm']} bpm "
                f"({noise['people_qualifying']} people; {noise['method']}).")

# ------------------------------------------------------------------------------------------- revision-informed
st.header("4 · Revision-informed checks (shown next to their v1 failure)")
if l45:
    l4 = l45["L4"]
    st.markdown(f"**L4, cross-shift creatinine in a heavy outdoor worker** ❌ still outside the "
                f"{l4['target_band_pct'][0]}-{l4['target_band_pct'][1]} % band: cross-shift AKI "
                f"{l4['v1_engine_before_revision']['share_end_of_shift_aki_pct']} % (v1) -> "
                f"{l4['twin_engine']['share_end_of_shift_aki_pct']} % (revised engine); mean end-of-shift rise "
                f"{l4['v1_engine_before_revision']['mean_end_of_shift_rise_mg_dl']} -> "
                f"{l4['twin_engine']['mean_end_of_shift_rise_mg_dl']} mg/dL; cross-shift eGFR fall "
                f"{l4['twin_engine']['mean_cross_shift_egfr_fall_pct']} %. Reference: {l4['reference']}. Stated "
                "limitation: the engine under-represents transient cross-shift creatinine rises in heavy outdoor "
                "workers; the next morning value returns to baseline, which supports the 08:00 labelling rule.")
    l5 = l45["L5"]
    st.markdown(f"**L5, volume to GFR** ℹ️: {l5['reference']}.")
    st.dataframe([{"body-mass loss": k, "v1 engine": v["ecf_share_0.5"],
                   "revised, dehydration only": l5["twin_engine_dehydration_only"][k]["ecf_share_0.5"],
                   "revised, with sustained exertion": l5["twin_engine_with_sustained_exertion"][k]["ecf_share_0.5"]}
                  for k, v in l5["v1_engine_gfr_fall_pct"].items()], hide_index=True, width="stretch")
    st.caption("GFR fall in % at ECF share 0.5.")

# ------------------------------------------------------------------------------------------- extras
st.header("5 · Robustness, subgroups and sensitivity (frozen model; reported as they came out)")
if not extra:
    st.info("Run `scripts/evaluate.py` to fill this section.")
else:
    rep = extra.get("reproduction", {})
    if rep:
        ok = all(m["reproduced"] for y in rep.values() for m in y["models"].values())
        st.markdown(f"**Reproduction** {verdict(ok, 'reproduced', 'differs')}: the frozen models on the re-generated "
                    "2025 / 2026 features give AUPRC " + "; ".join(
                        f"{y}: M {v['models']['M_hybrid_core25']['auprc_now']} (reported "
                        f"{v['models']['M_hybrid_core25']['auprc_reported']})" for y, v in rep.items()) + ".")
    rob = extra.get("robustness", {})
    if rob:
        names = {"headline_noisy_forecast": "headline (noisy forecast)", "perfect_forecast": "perfect forecast",
                 "no_band": "no wearable band", "tier0_only": "everyone Tier 0", "drop30": "30 % band days missing",
                 "drop50": "50 % band days missing", "noise2x": "sensor noise x2"}
        st.markdown(f"**Ablations and robustness** ({rob.get('season')} held-out season, {rob.get('patients')} test "
                    "patients, the same patients in every row)")
        st.dataframe([{"variant": names[k], "AUPRC": f"{v['auprc']} ({ci_text(v['auprc_ci95'])})",
                       "red sensitivity": f"{100 * v['sensitivity_red']:.0f} %",
                       "red per 100 pt-days": v["red_per_100_patient_days"],
                       "median lead (h)": v["median_lead_h"], "caught >= 24 h ahead": v["pct_caught_ge_24h_ahead"]}
                      for k, v in rob.items() if k in names], hide_index=True, width="stretch")
    sub = extra.get("subgroups", {})
    if sub:
        year = st.selectbox("Subgroups: season", list(sub))
        st.dataframe([{"group": g, "value": v, "patients": m["patients"], "positive days": m["positive_days"],
                       "episodes": m.get("episodes"), "AUPRC": m.get("auprc"),
                       "red sensitivity": None if m.get("sensitivity_red") is None else
                       f"{100 * m['sensitivity_red']:.0f} %", "red per 100 pt-days": m.get("red_per_100_patient_days")}
                      for g, vals in sub[year].items() for v, m in vals.items()],
                     hide_index=True, width="stretch", height=420)
    tor = extra.get("tornado", {})
    if tor:
        st.plotly_chart(charts.tornado(tor["top10"], tor["baseline_risk"],
                                       f"Top 10 assumptions: Riya's 72-h risk (baseline "
                                       f"{100 * tor['baseline_risk']:.1f} %)"),
                        width="stretch", theme="streamlit")
        st.caption(tor["output"] + f". {tor['parameters_screened']} registry assumptions screened; the drinking "
                   f"fraction (phi_drink) ranks {tor['phi_drink_rank']}.")
        st.dataframe([{"parameter": r["parameter"], "low": r["low"]["value"], "risk at low": r["low"]["risk"],
                       "high": r["high"]["value"], "risk at high": r["high"]["risk"], "swing": r["swing"]}
                      for r in tor["top10"]], hide_index=True, width="stretch")
