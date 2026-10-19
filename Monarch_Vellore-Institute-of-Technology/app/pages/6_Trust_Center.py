"""Trust Center: consent artefacts and revoke, the hash-chained audit log with signed checkpoints and a tamper demo,
the data-integrity gate (S10), FHIR R4 export, the DPDP mapping and what each role can see."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import streamlit as st
from components.api_client import services, session
from components.theme import frame

from vrikka.security import crypto, rbac
from vrikka.security.audit import tamper_demo
from vrikka.security.dpdp import DPDP_MAP

frame("Trust Center", "🛡️")
sv = services()
s = session()

tabs = st.tabs(["Consent", "Audit log", "Tamper demo", "Data-integrity gate", "FHIR export", "DPDP Act 2023",
                "Who sees what"])

with tabs[0]:
    st.markdown("Every read by a doctor, ASHA, lab or family member needs a **signed, unexpired ABDM-style consent "
                "artefact** for that patient, role, purpose and data type. It is checked on every read, so a revoke "
                "works at once (test S11). The patient manages it on the Patient and Family page.")
    if s is None or s.role not in ("doctor", "admin", "patient"):
        st.info("Log in as Patient (your own artefacts), Doctor or Admin to see consent artefacts.")
    else:
        pid = s.subject if s.role == "patient" else st.selectbox(
            "Patient", list(sv.patients), format_func=lambda i: sv.patients[i].get("label", i)[:80])
        st.dataframe(sv.consent_summary(s, pid), hide_index=True, width="stretch")
        if s.role == "patient":
            st.info("You can revoke or grant on the Patient and Family page.")
    st.caption("This demonstrates the ABDM consent pattern; no ABDM sandbox or gateway is called.")

with tabs[1]:
    if s is None or not rbac.allowed(s.role, "view_audit"):
        st.info("Log in as Admin or Doctor to see the audit log.")
    else:
        status = sv.audit_status(s)
        c = st.columns(4)
        c[0].metric("Records", status["records"])
        c[1].metric("Chain intact", "yes" if status["chain_intact"] else "NO")
        c[2].metric("Signed checkpoints", status["checkpoints"])
        c[3].metric("Checkpoints verify", "yes" if status["ok"] else "NO")
        st.caption(f"Checkpoint signing key (Ed25519, public): `{status['public_key']}`")
        st.dataframe([{"seq": r["seq"], "time": r["ts"], "actor": r["actor"], "action": r["action"],
                       "subject": r["subject"], "details": json.dumps(r["details"], ensure_ascii=False)[:120],
                       "mac": r["mac"][:16] + "..."} for r in reversed(sv.audit.records[-200:])],
                     hide_index=True, width="stretch", height=380)

with tabs[2]:
    st.markdown("Each record carries the HMAC of the one before it, so editing a record breaks the chain. A forger "
                "who stole the HMAC key could recompute every MAC; the **Ed25519-signed checkpoint** still catches "
                "that, because the head it signed no longer matches.")
    if st.button("Run the tamper demo"):
        d = tamper_demo()
        c = st.columns(3)
        c[0].markdown("**Before**")
        c[0].json({k: d["before"][k] for k in ("chain_intact", "ok")})
        c[1].markdown(f"**After editing record {d['edited_record']}**")
        c[1].json({k: d["after_edit"][k] for k in ("chain_intact", "first_bad_record", "ok")})
        c[2].markdown("**After a re-chained forgery**")
        c[2].json({k: d["after_rechained_forgery"][k] for k in ("chain_intact", "ok")})

with tabs[3]:
    st.markdown("Device readings pass the gate before the twin sees them: plausible ranges, weight jumps, stale or "
                "future time stamps, replayed nonces, and Ed25519 signatures for registered devices "
                "(`config/integrity.yaml`). Rejections are audited, never silently repaired.")
    if "dev_key" not in st.session_state:
        st.session_state["dev_key"] = crypto.new_signing_key()
        sv.gate.register_device("band-demo-signed", crypto.public_key_b64(st.session_state["dev_key"]))

    def message(device="band-demo", **readings):
        return {"device_id": device, "patient_id": "S1_kamala", "ts": datetime.now(UTC).isoformat(),
                "nonce": uuid.uuid4().hex, "readings": readings or {"weight_kg": 61.6, "resting_hr_bpm": 78}}

    c = st.columns(5)
    out = None
    if c[0].button("Normal reading"):
        st.session_state["last_msg"] = message()
        out = sv.ingest_device(st.session_state["last_msg"])
    if c[1].button("Weight 520 kg"):
        out = sv.ingest_device(message(weight_kg=520.0))
    if c[2].button("Replay the last message"):
        out = sv.ingest_device(st.session_state.get("last_msg") or message())
    if c[3].button("Unsigned, registered device"):
        out = sv.ingest_device(message("band-demo-signed"))
    if c[4].button("Signed reading"):
        m = message("band-demo-signed")
        m["signature"] = crypto.sign(st.session_state["dev_key"], sv.gate.signed_body(m))
        out = sv.ingest_device(m)
    if out is not None:
        (st.success if out["accepted"] else st.error)(
            "Accepted" if out["accepted"] else "Rejected: " + ", ".join(out["reasons"]))

with tabs[4]:
    if s is None or not rbac.allowed(s.role, "export_fhir"):
        st.info("Log in as Doctor or Patient to export a FHIR R4 bundle.")
    else:
        pid = s.subject if s.role == "patient" else st.selectbox("Patient ", list(sv.patients), key="fhir_pid")
        try:
            b = sv.export_fhir(s, pid)
            st.download_button("Download bundle", json.dumps(b, indent=1), file_name=f"{pid}_fhir.json")
            st.json(b, expanded=False)
        except rbac.AccessDenied as e:
            st.error(f"Access denied: {e.reason}")

with tabs[5]:
    st.dataframe(DPDP_MAP, hide_index=True, width="stretch")
    st.caption("A design mapping for a research prototype, not legal advice or a compliance certificate.")

with tabs[6]:
    st.dataframe([{"role": r, "actions": ", ".join(sorted(rbac.ACTIONS[r])),
                   "fields": "all" if rbac.FIELDS[r] is None else ", ".join(sorted(rbac.FIELDS[r]))}
                  for r in rbac.ROLES], hide_index=True, width="stretch")
    if st.button("Reset the demo (new keys, empty audit log, all consents granted)"):
        services.clear()
        st.session_state.pop("session", None)
        st.session_state.pop("dev_key", None)
        st.rerun()
