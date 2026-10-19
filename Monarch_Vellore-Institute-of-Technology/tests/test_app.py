"""Every Streamlit page runs headlessly (streamlit.testing AppTest) for the roles it serves, with no exception, and
role gates hold (Part 7)."""
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from vrikka.security import auth

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))
USERS = {"doctor": ("dr_demo", "doctor-demo"), "patient": ("riya", "patient-demo"),
         "family": ("riya_family", "family-demo"), "asha": ("asha_demo", "asha-demo"),
         "lab": ("lab_demo", "lab-demo"),
         "admin": ("admin_demo", "admin-demo")}


def run(page: str, role: str | None = None) -> AppTest:
    at = AppTest.from_file(str(APP / page), default_timeout=240)
    if role:
        at.session_state["session"] = auth.login(*USERS[role])
    at.run()
    return at


@pytest.mark.parametrize("page, role", [
    ("Home.py", None), ("pages/1_Doctor_Triage.py", "doctor"), ("pages/2_Patient_Twin.py", "doctor"),
    ("pages/2_Patient_Twin.py", "patient"), ("pages/3_Patient_Family.py", "patient"),
    ("pages/3_Patient_Family.py", "family"), ("pages/4_ASHA_Field.py", "asha"), ("pages/5_Lab_Tasks.py", "lab"),
    ("pages/6_Trust_Center.py", "admin"), ("pages/6_Trust_Center.py", None), ("pages/7_Time_Machine.py", None),
    ("pages/8_Evaluation.py", None),
])
def test_page_runs(page, role):
    at = run(page, role)
    assert not at.exception, [e.value for e in at.exception]


def test_role_gate_stops_the_wrong_role():
    at = run("pages/1_Doctor_Triage.py", "patient")
    assert not at.exception
    assert any("This page is for" in i.value for i in at.info)
    assert not at.dataframe                                  # no patient list was shown


def test_asha_page_defaults_to_telugu():
    at = run("pages/4_ASHA_Field.py", "asha")
    assert at.session_state["lang"] == "te"


@pytest.mark.parametrize("lang", ["en", "hi", "kn", "te"])
def test_visit_summary_is_in_the_patient_language_with_the_disclaimer(lang):
    from components.summary import visit_summary_html

    from vrikka.i18n import t
    from vrikka.services import Services

    sv = Services()
    rec = sv.read_patient(sv.login(*USERS["patient"]), "S1_riya")
    h = visit_summary_html(rec, lang)
    assert t("summary.disclaimer", lang) in h and t(f"level.{rec['level']}", lang) in h
    assert t(rec["reasons"][0], lang) in h
    assert "stop your" not in h.lower() and "<script" not in h.lower()


def test_kidney_weather_and_twin_fit_reports_exist():
    import json

    from vrikka.config import REPORTS_DIR

    kw = json.loads((REPORTS_DIR / "demo_triage_panel.json").read_text("utf-8"))["kidney_weather"]
    assert set(kw["cities"]) and all(v["red"] <= v["patients"] for v in kw["cities"].values())
    assert all(r["risk"] >= kw["suggested_tests_today"][-1]["risk"] for r in kw["suggested_tests_today"])
    tf = json.loads((REPORTS_DIR / "twin_fit.json").read_text("utf-8"))["personas"]["S1_riya"]
    assert len(tf["days"]) == 12 and all(len(d["theta_80"]) == 2 for d in tf["days"])
