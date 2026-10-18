"""Demo authentication (§21; Part 6): bcrypt-hashed demo passwords from settings (.env) and short-lived signed tokens
(PyJWT, HS256 with ``SECRET_KEY``). Demo accounts only; a deployment would use the hospital's identity provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import bcrypt
import jwt

from vrikka.config import settings

TOKEN_HOURS = 8

# username -> (role, subject the account is linked to). Personas are fictional.
DEMO_USERS = {
    "dr_demo": ("doctor", None),
    "kamala": ("patient", "S1_kamala"),
    "kamala_family": ("family", "S1_kamala"),
    "asha_demo": ("asha", None),
    "lab_demo": ("lab", None),
    "admin_demo": ("admin", None),
}


@dataclass(frozen=True)
class Session:
    username: str
    role: str
    subject: str | None
    token: str


@lru_cache(maxsize=1)
def _hashes() -> dict[str, bytes]:
    s = settings()
    pw = {"doctor": s.demo_doctor_password, "patient": s.demo_patient_password, "family": s.demo_family_password,
          "asha": s.demo_asha_password, "lab": s.demo_lab_password, "admin": s.demo_admin_password}
    return {u: bcrypt.hashpw(pw[r].encode(), bcrypt.gensalt(rounds=8)) for u, (r, _) in DEMO_USERS.items()}


def issue_token(username: str) -> str:
    role, subject = DEMO_USERS[username]
    now = datetime.now(UTC)
    return jwt.encode({"sub": username, "role": role, "subject": subject, "iat": now,
                       "exp": now + timedelta(hours=TOKEN_HOURS)}, settings().secret_key, algorithm="HS256")


def login(username: str, password: str) -> Session | None:
    h = _hashes().get(username)
    if h is None or not bcrypt.checkpw(password.encode(), h):
        return None
    role, subject = DEMO_USERS[username]
    return Session(username, role, subject, issue_token(username))


def session_from_token(token: str) -> Session | None:
    try:
        c = jwt.decode(token, settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if c.get("sub") not in DEMO_USERS:
        return None
    return Session(c["sub"], c["role"], c.get("subject"), token)
