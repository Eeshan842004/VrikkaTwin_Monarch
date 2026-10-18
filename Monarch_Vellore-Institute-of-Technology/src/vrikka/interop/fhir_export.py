"""FHIR R4 export (§21; Part 6): a ``collection`` Bundle with Patient, Observations (LOINC), the 72-hour kidney-injury
RiskAssessment and the Consent that allowed the export. Plain JSON dictionaries (no FHIR library); ``validate_bundle``
checks the structure the export promises (resource types, ids, references, codes, units).
Identifiers are pseudonymous; the personas are fictional.
"""
from __future__ import annotations

from datetime import UTC, datetime

from vrikka.interop.loinc import LOINC

LOINC_SYSTEM = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"


def _ref(kind: str, rid: str) -> dict:
    return {"reference": f"{kind}/{rid}"}


def patient_resource(pid: str, female: bool | None, age: float | None, now: datetime) -> dict:
    res = {"resourceType": "Patient", "id": pid,
           "identifier": [{"system": "urn:vrikkatwin:pseudonym", "value": pid}],
           "meta": {"tag": [{"system": "urn:vrikkatwin", "code": "synthetic", "display": "Fictional demo person"}]}}
    if female is not None:
        res["gender"] = "female" if female else "male"
    if age is not None:
        res["birthDate"] = str(now.year - int(age))
    return res


def observation(pid: str, idx: int, name: str, value: float, when: str) -> dict:
    code, display, unit = LOINC[name]
    return {"resourceType": "Observation", "id": f"{pid}-obs-{idx}", "status": "final",
            "code": {"coding": [{"system": LOINC_SYSTEM, "code": code, "display": display}]},
            "subject": _ref("Patient", pid), "effectiveDateTime": when,
            "valueQuantity": {"value": round(float(value), 4), "unit": unit, "system": UCUM, "code": unit}}


def risk_assessment(pid: str, risk: float, level: str, reasons: list[str], when: str, method: str) -> dict:
    return {"resourceType": "RiskAssessment", "id": f"{pid}-risk", "status": "final",
            "subject": _ref("Patient", pid), "occurrenceDateTime": when,
            "method": {"text": method},
            "prediction": [{"outcome": {"text": "kidney injury (KDIGO creatinine criteria) within 72 hours"},
                            "probabilityDecimal": round(float(risk), 4),
                            "qualitativeRisk": {"text": level},
                            "whenRange": {"high": {"value": 72, "unit": "h"}}}],
            "basis": [{"display": r} for r in reasons],
            "note": [{"text": "Research prototype; not a diagnosis. Synthetic validation only."}]}


def consent_resource(pid: str, artefact) -> dict:
    return {"resourceType": "Consent", "id": f"{pid}-consent-{artefact.requester}",
            "status": "active" if artefact.status == "GRANTED" else "inactive",
            "scope": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/consentscope",
                                  "code": "patient-privacy"}]},
            "category": [{"coding": [{"system": "http://loinc.org", "code": "59284-0"}]}],
            "patient": _ref("Patient", pid), "dateTime": artefact.date_from,
            "provision": {"period": {"start": artefact.date_from, "end": artefact.date_to},
                          "actor": [{"role": {"text": artefact.requester},
                                     "reference": {"display": artefact.requester}}],
                          "purpose": [{"system": "urn:abdm:purpose", "code": artefact.purpose}]},
            "identifier": [{"system": "urn:vrikkatwin:consent", "value": artefact.consent_id}]}


def export_bundle(record: dict, consent=None, now: datetime | None = None) -> dict:
    """record: patient_id, female, age, observations [(name, value, iso time)], risk, level, reasons, method."""
    now = now or datetime.now(UTC)
    pid = record["patient_id"]
    stamp = now.isoformat(timespec="seconds")
    entries = [patient_resource(pid, record.get("female"), record.get("age"), now)]
    for i, (name, value, when) in enumerate(record.get("observations", [])):
        entries.append(observation(pid, i, name, value, when))
    if record.get("risk") is not None:
        entries.append(risk_assessment(pid, record["risk"], record.get("level", ""), record.get("reasons", []),
                                       stamp, record.get("method", "VrikkaTwin fast clock")))
    if consent is not None:
        entries.append(consent_resource(pid, consent))
    return {"resourceType": "Bundle", "type": "collection", "timestamp": stamp,
            "entry": [{"fullUrl": f"urn:uuid:{e['resourceType']}-{e['id']}", "resource": e} for e in entries]}


def validate_bundle(b: dict) -> list[str]:
    """Structural checks; returns a list of problems (empty = valid for what this export promises)."""
    problems = []
    if b.get("resourceType") != "Bundle" or b.get("type") != "collection":
        problems.append("not a collection Bundle")
    ids = {(e["resource"]["resourceType"], e["resource"]["id"]) for e in b.get("entry", [])}
    for e in b.get("entry", []):
        r = e["resource"]
        if not r.get("id"):
            problems.append(f"{r.get('resourceType')} without id")
        ref = (r.get("subject") or r.get("patient") or {}).get("reference")
        if ref:
            kind, rid = ref.split("/", 1)
            if (kind, rid) not in ids:
                problems.append(f"dangling reference {ref}")
        if r["resourceType"] == "Observation":
            c = r["code"]["coding"][0]
            if c["system"] != LOINC_SYSTEM or not c["code"]:
                problems.append(f"{r['id']} without a LOINC code")
            if "unit" not in r.get("valueQuantity", {}):
                problems.append(f"{r['id']} without a unit")
        if r["resourceType"] == "RiskAssessment":
            p = r["prediction"][0]["probabilityDecimal"]
            if not 0 <= p <= 1:
                problems.append("probability outside [0, 1]")
    return problems
