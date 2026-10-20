"""ASHA Tier-0 field page (Telugu by default): the people she visits, the red-flag form built from
config/red_flags.yaml, and a text check-in with medicine brand read-back. Red flags run before any risk."""
from __future__ import annotations

import streamlit as st
from components.alerts import ambulance_button, medicines_panel
from components.api_client import require, services
from components.cards import brand_readback, checkin_form, screen
from components.theme import badge, frame

from vrikka.i18n import t

if "asha_lang_set" not in st.session_state:          # Tier-0 demo is in Telugu unless the user changes it
    st.session_state["lang"] = "te"
    st.session_state["asha_lang_set"] = True
frame("ASHA Field (Tier 0)", "🧑🏽‍⚕️")
s = require("asha")
sv = services()
L = st.session_state.get("lang", "te")

rows = sv.list_triage(s)
st.markdown(f"**{t('ui.patient_select', L)}**")
st.dataframe([{"level": t(f"level.{r['level']}", L), "name": r.get("name"), "city": r.get("city"),
               "tier": r.get("tier"), "last red flag": r.get("red_flags")} for r in rows],
             hide_index=True, width="stretch", height=240)
pick = st.selectbox(t("ui.patient_select", L), [r["patient_id"] for r in rows],
                    format_func=lambda i: next(r.get("name") or i for r in rows if r["patient_id"] == i))
rec = sv.read_patient(s, pick)
st.markdown(badge(rec["level"], L) + f" &nbsp; {t('action.' + rec['level'], L)}", unsafe_allow_html=True)
ambulance_button(sv, s, pick, L, "asha_amb_top")
with st.expander(t("ui.meds_title", L)):
    medicines_panel(sv, s, pick, L, f"asha_meds_{pick}")

got = checkin_form("asha_checkin", L, "ui.checkin_asha_title")
if got:
    fields, text = got
    brand_readback(text, L)
    res = sv.submit_checkin(s, pick, L, fields, text or None)
    screen(res, L)
    if res["level"] == "emergency":
        ambulance_button(sv, s, pick, L, "asha_amb_flag")
    if res["minimum_alert_level"]:
        st.caption(f"Minimum alert level for the doctor: {res['minimum_alert_level']}. Logged in the audit trail.")

with st.expander("Previous check-ins"):
    st.dataframe([{"time": c["ts"], "by": c["role"], "red flag": c["red_flag"], "text": c["text"]}
                  for c in rec.get("checkins", [])], hide_index=True, width="stretch")
