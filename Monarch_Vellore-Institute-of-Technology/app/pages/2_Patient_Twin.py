"""Patient Twin: the twin's state, what-if levers (in the agreed order, with guardrails) and the slow clock."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st
from components import charts
from components.api_client import require, services
from components.reports import report
from components.theme import SEQ, badge, frame, lang
from components.twin_live import active_events, patient_context, replay_ctx, twin_state

from vrikka.config import param
from vrikka.fastclock.display import modelled_filtration, risk_text
from vrikka.i18n import t
from vrikka.slowclock.bayes_slope import fit
from vrikka.slowclock.projection import AkiEpisode, Scenario, project, wording
from vrikka.whatif.levers import available_levers, run_levers
from vrikka.whatif.sickday import guidance

frame("Patient Twin", "💧")
s = require("doctor", "patient")
sv = services()
L = lang()

personas = [r for r in sv.list_triage(s) if r.get("risk_basis") == "twin_simulation"] if s.role == "doctor" else \
    [sv.read_patient(s, s.subject)]
names = {r["patient_id"]: r.get("name", r["patient_id"]) for r in personas}
pid = st.selectbox("Persona (fictional)", list(names), format_func=lambda i: names[i]) if len(names) > 1 else \
    next(iter(names))
rec = sv.read_patient(s, pid)
full = sv.patients[pid]                     # dates / days are not personal data; the record above is role-filtered
dates = full["dates"]
day = st.select_slider("Day of the demo heatwave (replay on real 2024 weather)", options=list(range(len(dates))),
                       value=full["today"], format_func=lambda d: dates[d] if dates else str(d))
rep = replay_ctx(pid, day)
ctx = rep.context
st_ = twin_state(ctx["twin"])
risk = rep.risk[day]
level = rep.levels[day]

st.markdown(f"#### {rec.get('name', pid)} · {full['label']}")
c = st.columns(5)
c[0].markdown(badge(level, L), unsafe_allow_html=True)
c[0].markdown(f"**{risk_text(risk, int(param('mc_draws_ui')))['text']}**")
c[0].caption("72-h simulated risk")
c[1].metric(t("filtration.label", L), f"{modelled_filtration(st_['gfr_frac'])['value_pct']} %")
c[2].metric("Twin creatinine (08:00)", f"{st_['cr_mg_dl']:.2f} mg/dL", delta=f"x{st_['cr_ratio']:.2f} of baseline",
            delta_color="off")
c[3].metric("Extracellular fluid deficit", f"{st_['v_ecf_l']:.2f} L")
c[4].metric("Learned sweat multiplier", f"{st_['theta']:.2f}")
act = active_events(pid, day)
if act:
    st.caption("Reported today: " + ", ".join(act))

st.divider()
st.subheader("What if ... (72-hour twin simulation, same random draws for every row)")
pctx = patient_context(pid, act)
levers = available_levers(pctx)
if not levers:
    st.info("No lever applies to this person today (no painkiller, no relevant medicine, not an outdoor worker).")
chosen = []
for g, title in ((1, "1 · Painkiller"), (2, "2 · Fluids and work hours"), (3, "3 · Medicine pauses (last)")):
    group = [lv for lv in levers if lv["group"] == g]
    if not group:
        continue
    st.markdown(f"**{title}**")
    for lv in group:
        label = t(lv["label_key"], L)
        disabled = not lv["allowed"]
        if st.checkbox(label, value=lv["allowed"] and g < 3, disabled=disabled, key=f"lv_{pid}_{lv['name']}"):
            chosen.append(lv["name"])
        notes = []
        if lv["badge_key"]:
            notes.append(("🏷️ " if g == 3 else "ℹ️ ") + t(lv["badge_key"], L))
        if lv["reason_key"]:
            notes.append(t(lv["reason_key"], L))
        notes += ["⚠️ " + t(w, L) for w in lv["warning_keys"]]
        if disabled:
            notes.append("⛔ " + t("ors.doctor_advises", L) + " (" + ", ".join(t(r, L) for r in
                                                                       lv["blocked_reason_keys"]) + ")")
        if lv["name"] == "painkiller_swap":
            chk = lv["detail"]["paracetamol"]
            notes.append(f"Paracetamol after the swap: {chk['total_mg']:.0f} mg/day (limit {chk['ceiling_mg']:.0f})")
        for n in notes:
            st.caption(n)
rows = run_levers(ctx["twin"], ctx["future"], ctx["baseline_cr"], pctx, selected=chosen,
                  seed=ctx["seed_whatif"], sweat_fn=ctx["sweat_fn"])
shown = [r for r in rows if not r.get("skipped")]
labels = [t(r["label_key"], L) if r["name"] != "continue" else t("lever.continue", L) for r in shown]
cum = ["continue as is"] + [" + ".join(r["applied"]) for r in shown[1:]]
fig = go.Figure(go.Bar(x=[100 * r["risk"] for r in shown], y=[f"{i}. {lab}" for i, lab in enumerate(labels)],
                       orientation="h", marker=dict(color=[SEQ["dark"]] + [SEQ["light"]] * (len(shown) - 1)),
                       text=[r["text"] for r in shown], textposition="outside", cliponaxis=False,
                       customdata=cum, hovertemplate="%{customdata}<br>%{x:.1f} %<extra></extra>"))
fig.update_layout(height=80 + 46 * len(shown), margin=dict(l=10, r=40, t=30, b=10), hovermode="closest",
                  title=dict(text="72-h risk, levers added in order (cumulative)", x=0, font=dict(size=15)))
fig.update_xaxes(title_text="risk (%)", gridcolor="rgba(128,128,128,0.18)")
fig.update_yaxes(autorange="reversed")
st.plotly_chart(fig, width="stretch", theme="streamlit")
st.caption("A lever changes the twin's next-72-hour inputs; the difference between rows is the lever, not simulation "
           "noise. Medicine pauses are individualised and the clinician decides; nothing here tells a patient to stop "
           "a medicine.")

sick = guidance(pctx.generics, {"fever_excess_c": 1 if "fever" in act else 0,
                                "vomit_episodes": 1 if "gi" in act else 0},
                pctx.heart_failure, pctx.egfr, pctx.last_potassium)
if sick["sick_day"]:
    st.markdown("**Sick-day guidance**")
    for it in sick["items"]:
        st.markdown("- " + t(it["key"], L, generic=it["generic"] or "") + (
            f" ({t(it['reason_key'], L)})" if it["reason_key"] else ""))
    st.markdown("- " + t(sick["ors"]["advice_key"], L))

st.divider()
st.subheader("Slow clock: long-term eGFR ranges")
p = full
post = fit([(0.0, float(p["egfr_baseline"]))], egfr_now=float(p["egfr_baseline"]), dm=bool(p["dm"]),
           uacr_mg_g=p.get("uacr_mg_g"))
aki_t = report("slowclock_demo").get("aki_this_season_years", 0.0)
scen = [Scenario(label="continue as is"),
        Scenario(episodes=[AkiEpisode(aki_t, 1)], label="one stage-1 injury this season")]
if "sglt2" not in (full.get("chronic") or {}):
    scen.append(Scenario(sglt2i_start_years=0.0, label="start an SGLT2 inhibitor"))
prs = {sc.label: project(post, sc) for sc in scen}
first = next(iter(prs.values()))
st.plotly_chart(charts.fan(list(first.t_years),
                           {k: (list(v.low), list(v.median), list(v.high)) for k, v in prs.items()},
                           f"eGFR {100 * param('slow_band_low_q'):.0f}-{100 * param('slow_band_high_q'):.0f} % "
                           "ranges (prior group: " + post.group + ")",
                           {"G3a (60)": param("egfr_threshold_g3a"), "G4 (30)": param("egfr_threshold_g4"),
                            "G5 (15)": param("egfr_threshold_g5")}),
                width="stretch", theme="streamlit")
st.dataframe([{"scenario": k, "years to eGFR < 30": v.years_to["g4"]["text"],
               "years to eGFR < 15": v.years_to["g5"]["text"],
               "eGFR in 10 years (10-90 %)": f"{v.low[-1]:.0f}-{v.high[-1]:.0f}"} for k, v in prs.items()],
             hide_index=True, width="stretch")
for key in wording(bool(p["dm"]), has_aki_scenario=True):
    st.caption(t(key, L))
st.caption("Without serial eGFR the ranges are wide: each stable lab narrows them (Bayesian update).")
k = rec.get("kfre") or full.get("kfre") or {}
if k and not k.get("valid"):
    st.caption(t(k["reason_key"], L))
