"""Time Machine: replay a fictional persona's heatwave day by day (real 2024 weather, demo replay truth), with the
twin's risk, its creatinine estimate next to the simulated truth, and the naive heat-index rule for comparison."""
from __future__ import annotations

import streamlit as st
from components import charts
from components.reports import report
from components.theme import badge, frame, lang

from vrikka.config import load_yaml, param
from vrikka.fastclock.display import risk_text
from vrikka.services import directory

frame("Time Machine", "⏳")
L = lang()
ps = directory.personas()
nums = report("demo_numbers").get("scenarios", {})
pid = st.selectbox("Persona (fictional)", list(ps), format_func=lambda i: ps[i]["label"])
p = ps[pid]
n = nums.get(pid, {})
dates = p["dates"]
bands = load_yaml("alert_policy")["levels"]
day = st.slider("Day", 0, len(dates) - 1, p["today"], format="%d")
st.markdown(f"**{dates[day]}** &nbsp; " + badge(p["levels_by_day"][day], L)
            + f" &nbsp; twin 72-h risk {risk_text(p['risk_by_day'][day], int(param('mc_draws_ui')))['text']}",
            unsafe_allow_html=True)

c1, c2 = st.columns(2)
with c1:
    st.plotly_chart(charts.risk_trajectory(dates[: day + 1], p["risk_by_day"][: day + 1], p["levels_by_day"][: day + 1],
                                           "Twin 72-h simulated risk (as known each morning)", "risk (%)",
                                           bands={"red band": bands["amber"]["max_prob"],
                                                  "amber band": bands["green"]["max_prob"]}),
                    width="stretch", theme="streamlit")
with c2:
    base = p["cr_baseline"]
    st.plotly_chart(charts.lines(dates[: day + 1], {"twin estimate": p["twin_cr_0800"][: day + 1],
                                                    "demo replay truth": p["truth_cr_0800"][: day + 1]},
                                 "Creatinine at 08:00 (mg/dL)", "mg/dL",
                                 hline=(1.5 * base, "1.5 x baseline (KDIGO)")),
                    width="stretch", theme="streamlit")

sm = n.get("summary", {})
cols = st.columns(4)
cols[0].metric("Simulated injury (KDIGO stage 1+)", dates[sm["truth_aki_onset_day"]] if sm.get(
    "truth_aki_onset_day") is not None else "none")
cols[1].metric("First red day", dates[sm["first_red_day"]] if sm.get("first_red_day") is not None else "none")
cols[2].metric("Lead time", f"{sm['lead_time_h']} h" if sm.get("lead_time_h") is not None else "n/a")
cols[3].metric("Naive heat-index rule fired on", f"{sm.get('heat_index_rule_days', 0)} of {sm.get('days', 0)} days")
st.caption("Truth here is the physiology engine with the persona's true sweat and drinking (a demo replay). The "
           "twin starts from population priors and only sees the noisy morning weight and resting heart rate. "
           "With one prediction a day at 09:00 and creatinine read at 08:00, a warning on the morning before the "
           "injury is the earliest possible, so 'the day before' reads just under 24 h.")
if n.get("whatif_72h_risk"):
    st.markdown(f"**What-if on {dates[n['whatif_on_day']]}** (from `reports/demo_numbers.json`; live levers on the "
                "Patient Twin page)")
    st.dataframe([{"plan": k, "72-h risk": risk_text(v)["text"]}
                  for k, v in n["whatif_72h_risk"].items()], hide_index=True, width="stretch")
if pid == "S6_cyp2c9" and "normal_metaboliser_max_risk" in n:
    st.caption(f"Same tablets, CYP2C9 normal metaboliser: maximum risk {100 * n['normal_metaboliser_max_risk']:.1f} % "
               f"vs {100 * sm['max_risk']:.1f} % for *3/*3.")
