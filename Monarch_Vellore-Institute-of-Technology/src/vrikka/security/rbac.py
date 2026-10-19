"""Role-based access and field filtering (§21; Part 6). Every service call names an action; the role must allow it, and
the returned record keeps only the fields that role may see. Patients and family see their own (linked) record only.

Roles: doctor, patient, family, asha (Tier-0 field worker), lab (home kidney test), admin (trust and audit only; no
clinical data).
"""
from __future__ import annotations

ROLES = ("doctor", "patient", "family", "asha", "lab", "admin")

ACTIONS = {
    "doctor": {"read_patient", "list_triage", "order_test", "run_whatif", "export_fhir", "view_audit", "checkin"},
    "patient": {"read_patient", "run_whatif", "checkin", "manage_consent", "export_fhir"},
    "family": {"read_patient", "checkin"},
    "asha": {"read_patient", "list_triage", "checkin"},
    "lab": {"list_tasks", "record_result"},
    "admin": {"view_audit", "manage_devices"},
}

# Fields each role may see in a patient record (anything else is removed before it leaves the services layer).
FIELDS = {
    "doctor": None,                                  # None = every field
    "patient": {"patient_id", "name", "age", "female", "city", "language", "generics", "level", "risk", "risk_text",
                "advice_keys", "slow_clock", "checkins", "tasks", "label", "whatif", "sickday", "fictional",
                "reasons"},
    "family": {"patient_id", "name", "city", "language", "level", "risk_text", "advice_keys", "checkins", "label",
               "sickday", "fictional", "reasons"},
    "asha": {"patient_id", "name", "age", "female", "city", "language", "level", "advice_keys", "red_flags",
             "checkins", "tier", "label", "fictional"},
    "lab": {"patient_id", "age", "female", "tasks", "fictional"},
    "admin": {"patient_id"},
}

# Health-information type a role's read touches (checked against the consent artefact).
HI_TYPE = {"doctor": "RiskAssessment", "asha": "Observation", "lab": "DiagnosticReport", "family": "Observation"}

SELF_ROLES = {"patient"}                # a patient reading their own record needs no consent artefact


class AccessDenied(PermissionError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def allowed(role: str, action: str) -> bool:
    return action in ACTIONS.get(role, set())


def require(role: str, action: str) -> None:
    if not allowed(role, action):
        raise AccessDenied(f"role_cannot_{action}")


def filter_fields(role: str, record: dict) -> dict:
    keep = FIELDS[role]
    return dict(record) if keep is None else {k: v for k, v in record.items() if k in keep}
