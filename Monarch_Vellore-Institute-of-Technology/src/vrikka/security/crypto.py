"""Cryptography helpers for the trust layer (§21): Fernet field encryption for identifying data, Ed25519 signatures
for devices, consent artefacts and audit checkpoints. Keys come from settings (.env) or are generated per process for
the demo (``FERNET_KEY`` empty -> a fresh demo key; never reuse demo keys).
"""
from __future__ import annotations

import base64
import json
from functools import lru_cache

from cryptography.exceptions import InvalidSignature
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from vrikka.config import settings


def canonical(obj) -> bytes:
    """Deterministic JSON bytes for signing (sorted keys, no whitespace)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


# ------------------------------------------------------------------------------------------- Fernet (PII at rest)
@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = settings().fernet_key.strip()
    return Fernet(key.encode() if key else Fernet.generate_key())


def encrypt_text(text: str) -> str:
    return _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt_text(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return None


# ------------------------------------------------------------------------------------------- Ed25519
def new_signing_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def public_key_b64(key: Ed25519PrivateKey | Ed25519PublicKey) -> str:
    pub = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def load_public_key(b64: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(b64))


def sign(key: Ed25519PrivateKey, payload) -> str:
    return base64.b64encode(key.sign(canonical(payload))).decode("ascii")


def verify(public_key: Ed25519PublicKey | str, payload, signature_b64: str) -> bool:
    pub = load_public_key(public_key) if isinstance(public_key, str) else public_key
    try:
        pub.verify(base64.b64decode(signature_b64), canonical(payload))
        return True
    except (InvalidSignature, ValueError):
        return False
