"""Every Streamlit page runs headlessly (streamlit.testing AppTest) for the roles it serves, with no exception, and
role gates hold (Part 7)."""
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from vrikka.security import auth

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))
USERS = {"doctor": ("dr_demo", "doctor-demo"), "patient": ("kamala", "patient-demo"),
         "family": ("kamala_family", "family-demo"), "asha": ("asha_demo", "asha-demo"),
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
