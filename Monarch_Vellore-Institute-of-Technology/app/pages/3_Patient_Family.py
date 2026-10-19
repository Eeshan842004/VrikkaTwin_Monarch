"""Patient and Family: plain language in EN / HI / KN / TE with pre-generated audio, sick-day guidance, a check-in
that runs the red flags first, and (patient only) who can see the data, with a one-click revoke."""
from __future__ import annotations

import streamlit as st
from components.api_client import require, services
from components.cards import audio, brand_readback, checkin_form, screen
from components.theme import badge, frame, lang

from vrikka.i18n import t

frame("Patient and Family", "🏠")
s = require("patient", "family")
sv = services()
L = lang()
rec = sv.read_patient(s, s.subject)

st.subheader(t("ui.today_title" if s.role == "patient" else "ui.family_title", L))
st.caption(f"{rec.get('name', '')} · {t('ui.fictional', L)}")
c1, c2 = st.columns([1, 2])
with c1:
    st.markdown(badge(rec["level"], L), unsafe_allow_html=True)
    if rec.get("risk_text"):
        risk_line = rec['risk_text'].replace('95% interval', t('risk.interval', L))
        st.markdown(f"<div class='vt-hero'>{risk_line}</div><div class='vt-small'>{t('ui.risk_label', L)}"
                    "</div>", unsafe_allow_html=True)
with c2:
    st.markdown(f"**{t('ui.what_to_do', L)}**")
    st.markdown(f"### {t('action.' + rec['level'], L)}")
    st.markdown(f"🔊 {t('ui.listen', L)}")
    audio(L, f"level_{rec['level']}")

sick = rec.get("sickday") or {}
if sick.get("sick_day"):
    st.markdown(f"#### {t('ui.sickday_title', L)}")
    for it in sick["items"]:
        st.markdown("- " + t(it["key"], L, generic=it["generic"] or "")
                    + (f" ({t(it['reason_key'], L)})" if it["reason_key"] else ""))
    st.markdown("- " + t(sick["ors"]["advice_key"], L))
    if sick["ors"]["reason_keys"]:
        st.caption(", ".join(t(k, L) for k in sick["ors"]["reason_keys"]))

st.divider()
got = checkin_form("pf_checkin", L)
if got:
    fields, text = got
    brand_readback(text, L)
    res = sv.submit_checkin(s, s.subject, L, fields, text or None)
    screen(res, L)

if s.role == "patient":
    st.divider()
    st.markdown(f"#### {t('ui.consent_title', L)}")
    for row in sv.consent_summary(s, s.subject):
        c = st.columns([2, 1, 1])
        c[0].markdown(f"**{row['requester']}** · {row['status']} · until {row['expires_at'][:10]} · "
                      + ("signature ok" if row["signature_ok"] else "signature invalid"))
        if row["status"] == "GRANTED":
            if c[1].button(t("ui.revoke", L), key=f"rev_{row['requester']}"):
                sv.revoke_consent(s, s.subject, row["requester"])
                st.rerun()
        elif c[2].button(t("ui.grant", L), key=f"grant_{row['requester']}"):
            sv.grant_consent(s, s.subject, row["requester"])
            st.rerun()
    st.caption("Revoking takes effect at once: the next read by that role is refused and written to the audit log "
               "(see Trust Center).")
