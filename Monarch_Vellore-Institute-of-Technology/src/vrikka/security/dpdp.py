"""India's Digital Personal Data Protection Act, 2023: how this prototype maps to its main duties (Part 6; shown on
the Trust Center page). A design mapping for a demo, not legal advice or a compliance certificate; a deployment needs
a legal review and the DPDP Rules as notified.
"""
from __future__ import annotations

DPDP_MAP = [
    {"provision": "Section 4-6: consent (free, specific, informed, unambiguous; itemised notice)",
     "how": "ABDM-style consent artefact per requester and purpose, checked on every read; notice text on the "
            "patient page", "where": "interop/abdm_consent.py, security/consent.py, services"},
    {"provision": "Section 6(4): right to withdraw consent as easily as it was given",
     "how": "one-click revoke; every later read by that requester is refused and audited (test S11)",
     "where": "services.revoke_consent, tests/test_trust.py"},
    {"provision": "Section 8(3): accuracy and completeness of data used for decisions",
     "how": "data-integrity gate rejects implausible, stale, replayed or unsigned device readings (test S10)",
     "where": "security/device_gateway.py, config/integrity.yaml"},
    {"provision": "Section 8(5): reasonable security safeguards against breach",
     "how": "identifying fields encrypted at rest (Fernet), role-based field filtering, signed device messages, "
            "HMAC hash-chained audit log with Ed25519-signed checkpoints",
     "where": "security/crypto.py, security/rbac.py, security/audit.py"},
    {"provision": "Section 8(7): erase data when the purpose is served or consent is withdrawn",
     "how": "consent artefacts carry an expiry; the demo stores only synthetic data and can be reset",
     "where": "interop/abdm_consent.py"},
    {"provision": "Section 9: children's data (verifiable parental consent, no tracking)",
     "how": "the twin is not designed for people under 18 and refuses to compute a risk for them",
     "where": "whatif/guardrails.exclusion_check"},
    {"provision": "Section 11-13: rights to access, correction and grievance redressal",
     "how": "patients see their own record and audit trail entries; FHIR R4 export of their data",
     "where": "services.read_patient, interop/fhir_export.py"},
    {"provision": "Purpose limitation and data minimisation",
     "how": "each role sees only the fields it needs (ASHA: level and red flags; lab: the test task; admin: no "
            "clinical data)", "where": "security/rbac.py"},
]
