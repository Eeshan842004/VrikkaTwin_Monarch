"""Trust layer (Part 6): services enforce role + consent + audit; S10 (implausible feed rejected), S11 (consent
revoked), signed audit checkpoints and the tamper demo, ABDM-style consent, FHIR R4 export, Ed25519 device signing,
role-based field filtering and the FastAPI wrapper."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from vrikka.interop import abdm_consent as abdm
from vrikka.interop.fhir_export import validate_bundle
from vrikka.security import auth, crypto
from vrikka.security.audit import AuditLog, clone, tamper_demo
from vrikka.security.dpdp import DPDP_MAP
from vrikka.security.rbac import AccessDenied
from vrikka.services import Services


@pytest.fixture()
def sv():
    return Services()


def login(sv, user):
    pw = {"dr_demo": "doctor-demo", "riya": "patient-demo", "riya_family": "family-demo",
          "asha_demo": "asha-demo", "lab_demo": "lab-demo", "admin_demo": "admin-demo"}[user]
    s = sv.login(user, pw)
    assert s is not None
    return s


def msg(**kw):
    base = {"device_id": "band-01", "patient_id": "S1_riya", "ts": datetime.now(UTC).isoformat(),
            "nonce": uuid.uuid4().hex, "readings": {"weight_kg": 61.6, "resting_hr_bpm": 78}}
    return {**base, **kw}


# --------------------------------------------------------------------------------------------- S10
def test_s10_implausible_or_replayed_feeds_are_rejected_and_audited(sv):
    ok = sv.ingest_device(msg())
    assert ok == {"accepted": True, "reasons": []}
    bad = sv.ingest_device(msg(readings={"weight_kg": 520.0}))
    assert not bad["accepted"] and "implausible:weight_kg" in bad["reasons"]
    jump = sv.ingest_device(msg(readings={"weight_kg": 70.0}))                 # +8.4 kg in a day
    assert "implausible_jump:weight_kg" in jump["reasons"]
    hr = sv.ingest_device(msg(readings={"resting_hr_bpm": 300}))
    assert "implausible:resting_hr_bpm" in hr["reasons"]
    m = msg()
    assert sv.ingest_device(m)["accepted"]
    assert "replayed_nonce" in sv.ingest_device(m)["reasons"]
    old = msg(ts=(datetime.now(UTC) - timedelta(days=3)).isoformat())
    assert "stale_timestamp" in sv.ingest_device(old)["reasons"]
    rejected = [r for r in sv.audit.records if r["action"] == "device_reading_rejected"]
    assert len(rejected) == 5 and sv.audit.verify()


def test_registered_device_must_sign_with_ed25519(sv):
    key = crypto.new_signing_key()
    sv.gate.register_device("band-02", crypto.public_key_b64(key))
    m = msg(device_id="band-02")
    assert "bad_signature" in sv.ingest_device(dict(m))["reasons"]           # unsigned
    signed = {**m, "nonce": uuid.uuid4().hex}
    signed["signature"] = crypto.sign(key, sv.gate.signed_body(signed))
    assert sv.ingest_device(signed)["accepted"]
    forged = {**signed, "nonce": uuid.uuid4().hex, "readings": {"weight_kg": 61.0}}   # changed after signing
    assert "bad_signature" in sv.ingest_device(forged)["reasons"]


# --------------------------------------------------------------------------------------------- S11
def test_s11_revoked_consent_blocks_reads_and_is_audited(sv):
    dr, riya = login(sv, "dr_demo"), login(sv, "riya")
    assert sv.read_patient(dr, "S1_riya")["patient_id"] == "S1_riya"
    assert "S1_riya" in [r["patient_id"] for r in sv.list_triage(dr)]
    sv.revoke_consent(riya, "S1_riya", "doctor")
    with pytest.raises(AccessDenied) as e:
        sv.read_patient(dr, "S1_riya")
    assert e.value.reason == "consent_revoked"
    assert "S1_riya" not in [r["patient_id"] for r in sv.list_triage(dr)]
    with pytest.raises(AccessDenied):
        sv.export_fhir(dr, "S1_riya")
    denied = [r for r in sv.audit.records if r["action"] == "access_denied"]
    assert denied and denied[-1]["details"]["reason"] == "consent_revoked"
    assert sv.read_patient(login(sv, "asha_demo"), "S1_riya")          # other consents untouched
    sv.grant_consent(riya, "S1_riya", "doctor")
    assert sv.read_patient(dr, "S1_riya")
    assert sv.audit.verify_checkpoints()["ok"]


def test_consent_artefact_signature_expiry_and_scope():
    k = crypto.new_signing_key()
    a = abdm.grant("P1", "doctor", k, days=30)
    assert abdm.permits(a, "doctor", "RiskAssessment") == (True, "granted")
    assert abdm.permits(a, "asha", "RiskAssessment") == (False, "wrong_requester")
    assert abdm.permits(a, "doctor", "Observation", purpose="DSRCH") == (False, "wrong_purpose")
    assert abdm.permits(a, "doctor", "RiskAssessment", now=datetime.now(UTC) + timedelta(days=31))[1] == "expired"
    a.hi_types = ["Observation"]                                       # edited without re-signing
    assert abdm.permits(a, "doctor", "Observation") == (False, "bad_signature")
    assert abdm.permits(None, "doctor", "Observation") == (False, "no_consent")


# --------------------------------------------------------------------------------------------- roles
def test_patients_and_family_see_only_their_own_record(sv):
    riya, fam = login(sv, "riya"), login(sv, "riya_family")
    assert sv.read_patient(riya, "S1_riya")["name"] == "Riya"
    with pytest.raises(AccessDenied) as e:
        sv.read_patient(riya, "S3_fatima")
    assert e.value.reason == "not_your_record"
    rec = sv.read_patient(fam, "S1_riya")
    assert "risk" not in rec and "slow_clock" not in rec and rec["level"]
    with pytest.raises(AccessDenied):
        sv.read_patient(fam, "S2_ravi")


def test_role_field_filtering(sv):
    doc = sv.read_patient(login(sv, "dr_demo"), "S1_riya")
    asha = sv.read_patient(login(sv, "asha_demo"), "S1_riya")
    assert {"reasons", "slow_clock", "egfr_baseline", "generics"} <= set(doc)
    assert "reasons" not in asha and "slow_clock" not in asha and "egfr_baseline" not in asha
    assert {"level", "advice_keys", "name"} <= set(asha)
    admin = login(sv, "admin_demo")
    with pytest.raises(AccessDenied):
        sv.read_patient(admin, "S1_riya")
    lab = login(sv, "lab_demo")
    with pytest.raises(AccessDenied):
        sv.read_patient(lab, "S1_riya")


def test_order_test_lab_result_and_purple_level(sv):
    dr, lab = login(sv, "dr_demo"), login(sv, "lab_demo")
    with pytest.raises(AccessDenied):
        sv.order_kidney_test(lab, "S1_riya")
    tid = sv.order_kidney_test(dr, "S1_riya")
    assert [t["task_id"] for t in sv.list_tasks(lab, "ordered")] == [tid]
    base = sv.patients["S1_riya"]["cr_baseline"]
    res = sv.record_lab_result(lab, tid, base + 0.4, 4.8)
    assert res["flag"] == "kdigo_stage_1" and res["egfr_tag_key"] == "egfr.not_reliable"
    assert sv.read_patient(dr, "S1_riya")["level"] == "purple"
    tid2 = sv.order_kidney_test(dr, "S2_ravi")
    assert sv.record_lab_result(lab, tid2, sv.patients["S2_ravi"]["cr_baseline"], 6.2)["potassium_actions"] == [
        "same_day_repeat_potassium", "clinician_alert"]
    with pytest.raises(ValueError):
        sv.record_lab_result(lab, tid2, 85.0)                           # implausible mg/dL value


def test_checkin_runs_red_flags_first_and_stores_encrypted_text(sv):
    asha = login(sv, "asha_demo")
    out = sv.submit_checkin(asha, "S2_ravi", "te", text="స్పృహ లేదు")
    assert out["level"] == "emergency" and not out["show_risk"] and "108" in out["body"]
    raw = sv.con.execute("SELECT text_enc FROM checkins").fetchone()[0]
    assert "స్పృహ" not in raw                                          # encrypted at rest
    assert sv.read_patient(login(sv, "dr_demo"), "S2_ravi")["checkins"][0]["text"] == "స్పృహ లేదు"
    assert any(r["action"] == "red_flag" for r in sv.audit.records)


def test_wrong_password_is_refused_and_audited(sv):
    assert sv.login("dr_demo", "wrong") is None
    assert sv.audit.records[-1]["action"] == "login_failed"
    assert auth.session_from_token("not-a-token") is None


# --------------------------------------------------------------------------------------------- audit
def test_signed_checkpoints_catch_a_rechained_forgery():
    d = tamper_demo()
    assert d["before"]["ok"]
    assert not d["after_edit"]["ok"] and d["after_edit"]["first_bad_record"] == d["edited_record"]
    f = d["after_rechained_forgery"]
    assert f["chain_intact"] and not f["ok"], "MACs recomputed with a stolen key still fail the signed checkpoint"


def test_checkpoint_needs_the_right_public_key():
    log = AuditLog(key="k")
    log.append("x")
    log.checkpoint()
    other = crypto.public_key_b64(crypto.new_signing_key())
    assert log.verify_checkpoints()["ok"] and not log.verify_checkpoints(other)["ok"]
    c = clone(log)
    del c.records[0]
    assert not c.verify_checkpoints()["ok"]


# --------------------------------------------------------------------------------------------- interop / DPDP
def test_fhir_export_is_a_valid_r4_collection(sv):
    b = sv.export_fhir(login(sv, "dr_demo"), "S1_riya")
    assert validate_bundle(b) == []
    kinds = [e["resource"]["resourceType"] for e in b["entry"]]
    assert kinds[0] == "Patient" and "RiskAssessment" in kinds and "Consent" in kinds
    risk = next(e["resource"] for e in b["entry"] if e["resource"]["resourceType"] == "RiskAssessment")
    assert 0 <= risk["prediction"][0]["probabilityDecimal"] <= 1
    obs = [e["resource"] for e in b["entry"] if e["resource"]["resourceType"] == "Observation"]
    assert obs[0]["code"]["coding"][0]["code"] == "98979-8"


def test_dpdp_map_covers_consent_withdrawal_security_and_children():
    text = " ".join(r["provision"] for r in DPDP_MAP)
    for s in ("Section 6(4)", "Section 8(5)", "Section 9"):
        assert s in text


# --------------------------------------------------------------------------------------------- API wrapper
def test_api_wrapper_enforces_the_same_rules():
    from fastapi.testclient import TestClient

    from vrikka.api import deps
    from vrikka.api.main import app

    deps.services.cache_clear()
    c = TestClient(app)
    assert c.get("/health").json()["status"] == "ok"
    assert c.get("/triage").status_code == 401
    tok = c.post("/login", json={"username": "dr_demo", "password": "doctor-demo"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert c.get("/triage", headers=h).status_code == 200
    assert c.get("/patients/S1_riya", headers=h).json()["patient_id"] == "S1_riya"
    ptok = c.post("/login", json={"username": "riya", "password": "patient-demo"}).json()["token"]
    ph = {"Authorization": f"Bearer {ptok}"}
    assert c.get("/patients/S3_fatima", headers=ph).status_code == 403
    assert c.post("/patients/S1_riya/consent/revoke", json={"requester": "doctor"}, headers=ph).status_code == 200
    r = c.get("/patients/S1_riya", headers=h)
    assert r.status_code == 403 and r.json()["detail"] == "consent_revoked"
    bad = c.post("/devices/readings", json=msg(readings={"weight_kg": 900}))
    assert bad.json()["accepted"] is False
    deps.services.cache_clear()
