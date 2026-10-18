"""Consent registry (§21; Part 6): one ABDM-style artefact per (patient, requester role), signed by the demo consent
manager. ``check`` is called on every read by the services layer; ``revoke`` is the patient's revoke button (S11).
"""
from __future__ import annotations

from vrikka.interop import abdm_consent as abdm
from vrikka.security import crypto


class ConsentRegistry:
    def __init__(self, signer=None):
        self.signer = signer or crypto.new_signing_key()
        self.artefacts: dict[tuple[str, str], abdm.ConsentArtefact] = {}

    def grant(self, patient_id: str, requester: str, purpose: str = "CAREMGT", days: int = 90) -> abdm.ConsentArtefact:
        a = abdm.grant(patient_id, requester, self.signer, purpose=purpose, days=days)
        self.artefacts[(patient_id, requester)] = a
        return a

    def get(self, patient_id: str, requester: str) -> abdm.ConsentArtefact | None:
        return self.artefacts.get((patient_id, requester))

    def revoke(self, patient_id: str, requester: str | None = None) -> list[abdm.ConsentArtefact]:
        """Revoke one requester's artefact, or every artefact of the patient (requester None)."""
        out = []
        for (pid, req), a in self.artefacts.items():
            if pid == patient_id and (requester is None or req == requester) and a.status == "GRANTED":
                out.append(abdm.revoke(a, self.signer))
        return out

    def check(self, patient_id: str, requester: str, hi_type: str, purpose: str = "CAREMGT") -> tuple[bool, str]:
        return abdm.permits(self.get(patient_id, requester), requester, hi_type, purpose)

    def summary(self, patient_id: str) -> list[dict]:
        return [{"requester": req, "status": a.status, "purpose": a.purpose, "expires_at": a.expires_at,
                 "consent_id": a.consent_id, "signature_ok": abdm.signature_ok(a)}
                for (pid, req), a in self.artefacts.items() if pid == patient_id]
