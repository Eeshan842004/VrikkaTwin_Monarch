"""Alerts to doctor / family / patient, the ambulance button and the daily-medicine list (services layer)."""
import pytest

from vrikka.config import load_yaml
from vrikka.security.rbac import AccessDenied
from vrikka.services import Services
from vrikka.whatif.red_flags import LANGUAGES

PID = "S1_riya"


@pytest.fixture
def sv():
    return Services()


def login(sv, user):
    pw = {"dr_demo": "doctor-demo", "riya": "patient-demo", "riya_family": "family-demo", "asha_demo": "asha-demo",
          "lab_demo": "lab-demo"}[user]
    return sv.login(user, pw)


def test_red_risk_alert_reaches_patient_family_and_doctor(sv):
    assert sv.patients[PID]["level"] == "red"
    for user in ("riya", "riya_family", "dr_demo"):
        box = sv.inbox(login(sv, user))
        assert any(r["patient_id"] == PID and r["kind"] == "risk_alert" for r in box), user


def test_amber_alerts_skip_the_doctor(sv):
    doc = login(sv, "dr_demo")
    amber = {p for p, r in sv.patients.items() if r.get("level") == "amber"}
    assert amber and not any(r["patient_id"] in amber and r["kind"] == "risk_alert" for r in sv.inbox(doc))


def test_emergency_red_flag_alerts_everyone(sv):
    fam = login(sv, "riya_family")
    res = sv.submit_checkin(fam, PID, "en", {"confusion": True})
    assert res["level"] == "emergency"
    for user in ("riya", "riya_family", "dr_demo"):
        assert any(r["kind"] == "red_flag" and r["level"] == "emergency" for r in sv.inbox(login(sv, user))), user


def test_ambulance_button_logs_and_alerts(sv):
    res = sv.call_ambulance(login(sv, "riya"), PID)
    assert res["dial"] == "108" and set(res["notified"]) == {"patient", "doctor", "family"}
    assert any(r["action"] == "ambulance_called" and r["subject"] == PID for r in sv.audit.records)
    assert sv.inbox(login(sv, "dr_demo"))[0]["kind"] == "ambulance"
    with pytest.raises(AccessDenied):
        sv.call_ambulance(login(sv, "lab_demo"), PID)


def test_revoked_family_gets_no_new_alerts(sv):
    pat = login(sv, "riya")
    sv.revoke_consent(pat, PID, "family")
    sent = sv.call_ambulance(pat, PID)["notified"]
    assert "family" not in sent and "doctor" in sent


def test_medicine_list_starts_from_ehr_and_brands_resolve(sv):
    pat = login(sv, "riya")
    ehr = [m["name"] for m in sv.list_medicines(pat, PID)]
    assert ehr == sv.patients[PID]["generics"] and all(m["added_by"] == "EHR" for m in sv.list_medicines(pat, PID))
    r = sv.add_medicine(pat, PID, "Telma-H", "1 tablet", 1)
    assert r["recognised"] and r["generics"] == ["telmisartan", "hydrochlorothiazide"]
    r = sv.add_medicine(pat, PID, "some herbal tonic")
    assert not r["recognised"] and r["generics"] == []


def test_adding_a_painkiller_to_bp_pill_and_water_tablet_raises_triple_whammy(sv):
    fam = login(sv, "riya_family")
    r = sv.add_medicine(fam, PID, "Combiflam", "1 tablet", 3)
    assert r["warnings"] == ["notify.triple_whammy"]
    assert "ibuprofen" in sv.patients[PID]["generics"]
    assert any(n["kind"] == "medicine" for n in sv.inbox(login(sv, "dr_demo")))
    assert not sv.add_medicine(fam, PID, "Dolo")["warnings"], "paracetamol is not a triple-whammy drug"


def test_stopping_a_medicine_updates_the_list(sv):
    doc = login(sv, "dr_demo")
    r = sv.add_medicine(doc, PID, "Brufen")
    sv.stop_medicine(doc, PID, r["med_id"])
    assert "ibuprofen" not in sv.patients[PID]["generics"]
    assert all(m["med_id"] != r["med_id"] for m in sv.list_medicines(doc, PID))


def test_medicine_rights_follow_roles_and_own_record(sv):
    with pytest.raises(AccessDenied):
        sv.add_medicine(login(sv, "lab_demo"), PID, "Dolo")
    other = next(p for p in sv.patients if p != PID)
    with pytest.raises(AccessDenied):
        sv.add_medicine(login(sv, "riya"), other, "Dolo")


def test_new_strings_exist_in_every_language():
    keys = [k for k in load_yaml("i18n/en") if k.startswith(("notify.", "ui.meds_", "ui.ambulance", "ui.inbox"))]
    assert len(keys) >= 15
    for lang in LANGUAGES:
        assert all(k in load_yaml(f"i18n/{lang}") for k in keys), lang
