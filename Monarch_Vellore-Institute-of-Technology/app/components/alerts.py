"""Alerts inbox (sidebar), the emergency / ambulance button and the daily-medicines panel. All three go through the
services layer, so role, consent and the audit log apply to every click."""
from __future__ import annotations

import streamlit as st

from vrikka.i18n import t
from vrikka.security import rbac

ICON = {"emergency": "🚨", "red": "⛔", "urgent": "⚠️", "amber": "⚠️", "info": "ℹ️"}


def inbox_sidebar(sv, s, lang: str) -> None:
    """🔔 Alerts for the logged-in doctor, patient or family member (latest first)."""
    if not rbac.allowed(s.role, "read_notifications"):
        return
    rows = sv.inbox(s)
    unread = [r for r in rows if not r["read"]]
    with st.expander(f"🔔 {t('ui.inbox', lang)} ({len(unread)})", expanded=bool(unread) and s.role != "doctor"):
        if not rows:
            st.caption(t("ui.no_notifications", lang))
            return
        for r in rows[:8]:
            who = f"**{r['patient_name']}** · " if s.role == "doctor" else ""
            dot = "🔵 " if not r["read"] else ""
            st.markdown(f"{dot}{ICON.get(r['level'], '•')} {who}{t(r['message_key'], lang)}")
            st.caption(f"{r['ts'][:16].replace('T', ' ')} UTC · {r['source']}"
                       + (f" · {r['detail']}" if r["detail"] else ""))
        if len(rows) > 8:
            st.caption(f"+ {len(rows) - 8} more")
        if unread and st.button(t("ui.mark_read", lang), key="inbox_mark_read"):
            sv.mark_read(s, [r["notif_id"] for r in unread])
            st.rerun()


def ambulance_button(sv, s, pid: str, lang: str, key: str) -> None:
    """One press: log the emergency, alert the doctor and family, and offer the 108 dial link."""
    flag = f"amb_{key}_{pid}"
    if st.button(t("ui.ambulance_button", lang), key=key, type="primary", width="stretch"):
        st.session_state[flag] = sv.call_ambulance(s, pid)
    res = st.session_state.get(flag)
    if res:
        st.error(f"🚨 {t('ui.ambulance_called', lang)} ({', '.join(res['notified'])})")
        st.link_button(t("ui.ambulance_dial", lang, number=res["dial"]), f"tel:{res['dial']}", width="stretch")


def medicines_panel(sv, s, pid: str, lang: str, key: str) -> None:
    """The person's daily medicine list: see it, add a medicine (brand or generic), mark one as stopped."""
    editable = rbac.allowed(s.role, "manage_medicines")
    st.markdown(f"#### {t('ui.meds_title', lang)}")
    meds = sv.list_medicines(s, pid)
    if not meds:
        st.caption(t("ui.meds_none", lang))
    for m in meds:
        c = st.columns([3, 3, 2, 1] if editable else [3, 3, 2])
        c[0].markdown(f"**{m['name']}**")
        c[1].caption(", ".join(m["generics"]) if m["generics"] else "?")
        c[2].caption(" · ".join(x for x in (m["dose"] or "", f"{m['times_per_day']}x/day" if m["times_per_day"] else "",
                                             t("ui.meds_source_ehr", lang) if m["added_by"] == "EHR" else "") if x))
        if editable and c[3].button("✖", key=f"{key}_stop_{m['med_id']}", help=t("ui.meds_stop", lang)):
            sv.stop_medicine(s, pid, m["med_id"])
            st.rerun()
    if not editable:
        return
    with st.form(f"{key}_add", clear_on_submit=True):
        st.markdown(f"**{t('ui.meds_add', lang)}**")
        c = st.columns([3, 2, 1])
        name = c[0].text_input(t("ui.meds_name", lang))
        dose = c[1].text_input(t("ui.meds_dose", lang))
        times = c[2].number_input(t("ui.meds_times", lang), min_value=1, max_value=6, value=1, step=1)
        if st.form_submit_button(t("ui.meds_add", lang)) and name.strip():
            st.session_state[f"{key}_last"] = sv.add_medicine(s, pid, name, dose, int(times))
            st.rerun()
    res = st.session_state.pop(f"{key}_last", None)
    if res:
        if res["recognised"]:
            st.success(t("ui.meds_recognised", lang, generics=" + ".join(res["generics"])))
        else:
            st.warning(t("ui.meds_unrecognised", lang))
        for w in res["warnings"]:
            st.error(f"⛔ {t(w, lang)}")
