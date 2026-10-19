"""Lab Tasks: home kidney test orders from the doctor; entering a result turns a confirmed injury purple."""
from __future__ import annotations

import streamlit as st
from components.api_client import require, services
from components.theme import frame

from vrikka.i18n import t

frame("Lab Tasks (home kidney test)", "🧪")
s = require("lab")
sv = services()

open_tasks = sv.list_tasks(s, "ordered")
st.markdown(f"**Open orders: {len(open_tasks)}**")
if not open_tasks:
    st.info("No open orders. A doctor creates one with 'Order home kidney test' on Doctor Triage.")
for task in open_tasks:
    with st.form(f"task_{task['task_id']}"):
        st.markdown(f"**Task {task['task_id']}** · patient `{task['patient_id']}` · ordered by {task['ordered_by']} at "
                    f"{task['ordered_at']} · reason: {task['reason']}")
        c = st.columns(2)
        cr = c[0].number_input("Creatinine (mg/dL)", min_value=0.0, value=None, step=0.01)
        k = c[1].number_input("Potassium (mmol/L)", min_value=0.0, value=None, step=0.1)
        if st.form_submit_button("Save result", type="primary"):
            try:
                res = sv.record_lab_result(s, task["task_id"], cr, k)
            except ValueError as e:
                st.error(f"Rejected by the data-integrity gate: {e}")
            else:
                msg = f"Saved: {res['flag'].replace('_', ' ')}"
                if res["egfr"] is not None:
                    msg += f"; eGFR {res['egfr']:.0f}"
                    if res["egfr_tag_key"]:
                        msg += f" ({t(res['egfr_tag_key'])})"
                st.success(msg)
                for n in res["notes"]:
                    st.warning(t(n))
                if res["potassium_actions"]:
                    st.warning("Actions: " + ", ".join(a.replace("_", " ") for a in res["potassium_actions"]))

st.divider()
st.markdown("**All tasks**")
st.dataframe(sv.list_tasks(s), hide_index=True, width="stretch")
