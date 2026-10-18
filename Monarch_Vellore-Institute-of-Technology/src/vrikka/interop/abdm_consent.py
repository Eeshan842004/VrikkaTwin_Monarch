"""ABDM-style consent artefact (master plan §21; Part 6). Modelled on the shape of the Ayushman Bharat Digital Mission
consent artefact (purpose, patient, requester, health-information types, permission with access mode, date range and
expiry, status), signed by the consent manager with Ed25519. This is a DEMO of the pattern, not an ABDM integration:
no ABDM sandbox or gateway is called.

Every read in the services layer calls :func:`permits`; a revoked, expired or unsigned artefact never permits a read.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta

from vrikka.security import crypto

PURPOSES = {"CAREMGT": "Care management", "BTG": "Break the glass (emergency)", "PUBHLTH": "Public health",
            "HPAYMT": "Healthcare payment", "DSRCH": "Disease-specific research", "PATRQT": "Self-requested"}
HI_TYPES = ("Observation", "DiagnosticReport", "RiskAssessment", "MedicationRequest", "Consent")


@dataclass
class ConsentArtefact:
    patient_id: str
    requester: str                          # role or organisation allowed to read (e.g. "doctor", "asha", "lab")
    purpose: str = "CAREMGT"
    hi_types: list[str] = field(default_factory=lambda: list(HI_TYPES))
    access_mode: str = "VIEW"
    date_from: str = ""
    date_to: str = ""
    expires_at: str = ""
    status: str = "GRANTED"                 # GRANTED / REVOKED / EXPIRED
    consent_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    signature: str = ""
    signer_public_key: str = ""

    def body(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k not in ("signature", "signer_public_key")}


def grant(patient_id: str, requester: str, signer, purpose: str = "CAREMGT", days: int = 90,
          hi_types: list[str] | None = None, now: datetime | None = None) -> ConsentArtefact:
    now = now or datetime.now(UTC)
    if purpose not in PURPOSES:
        raise ValueError(f"unknown purpose {purpose}")
    a = ConsentArtefact(patient_id=patient_id, requester=requester, purpose=purpose,
                        hi_types=list(hi_types or HI_TYPES),
                        date_from=(now - timedelta(days=365)).isoformat(timespec="seconds"),
                        date_to=(now + timedelta(days=days)).isoformat(timespec="seconds"),
                        expires_at=(now + timedelta(days=days)).isoformat(timespec="seconds"))
    return sign(a, signer)


def sign(a: ConsentArtefact, signer) -> ConsentArtefact:
    a.signature = crypto.sign(signer, a.body())
    a.signer_public_key = crypto.public_key_b64(signer)
    return a


def revoke(a: ConsentArtefact, signer) -> ConsentArtefact:
    a.status = "REVOKED"
    return sign(a, signer)


def signature_ok(a: ConsentArtefact) -> bool:
    return bool(a.signature) and crypto.verify(a.signer_public_key, a.body(), a.signature)


def permits(a: ConsentArtefact | None, requester: str, hi_type: str, purpose: str = "CAREMGT",
            now: datetime | None = None) -> tuple[bool, str]:
    """(allowed, reason). Checked on every read."""
    if a is None:
        return False, "no_consent"
    now = now or datetime.now(UTC)
    if not signature_ok(a):
        return False, "bad_signature"
    if a.status != "GRANTED":
        return False, a.status.lower()
    if a.expires_at and now > datetime.fromisoformat(a.expires_at):
        return False, "expired"
    if a.requester != requester:
        return False, "wrong_requester"
    if a.purpose != purpose:
        return False, "wrong_purpose"
    if hi_type not in a.hi_types:
        return False, "hi_type_not_covered"
    return True, "granted"
