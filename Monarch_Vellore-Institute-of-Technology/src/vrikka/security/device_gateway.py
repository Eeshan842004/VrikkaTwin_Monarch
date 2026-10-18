"""Data-integrity gate for device and check-in feeds (§21; Part 6, test S10). Rules in config/integrity.yaml.

A message is {"device_id", "patient_id", "ts" (ISO time), "nonce", "readings": {name: value}, "signature"?}.
It is ACCEPTED only if every reading is plausible (and the weight did not jump implausibly since the last accepted
weight), the time stamp is fresh, the nonce has not been seen before (replay), and - for a device that registered an
Ed25519 public key - the signature verifies. Rejections are never clipped or repaired silently: the reasons are
returned and audited, and the twin never sees the message.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from vrikka.config import load_yaml
from vrikka.security import crypto


class IntegrityGate:
    def __init__(self, audit=None):
        self.cfg = load_yaml("integrity")
        self.audit = audit
        self.device_keys: dict[str, str] = {}             # device_id -> Ed25519 public key (base64)
        self.seen_nonces: set[tuple[str, str]] = set()
        self.last_weight: dict[str, float] = {}           # patient_id -> last accepted weight

    def register_device(self, device_id: str, public_key_b64: str) -> None:
        self.device_keys[device_id] = public_key_b64
        if self.audit is not None:
            self.audit.append("device_registered", actor="admin", subject=device_id)

    @staticmethod
    def signed_body(msg: dict) -> dict:
        return {k: v for k, v in msg.items() if k != "signature"}

    def check(self, msg: dict, now: datetime | None = None) -> tuple[bool, list[str]]:
        """(accepted, reasons). Does not change state."""
        now = now or datetime.now(UTC)
        reasons = []
        plaus = self.cfg["plausible"]
        for name, value in msg.get("readings", {}).items():
            rule = plaus.get(name)
            if rule is None:
                reasons.append(f"unknown_reading:{name}")
                continue
            try:
                v = float(value)
            except (TypeError, ValueError):
                reasons.append(f"not_a_number:{name}")
                continue
            if not rule["min"] <= v <= rule["max"]:
                reasons.append(f"implausible:{name}")
            if name == "weight_kg" and msg.get("patient_id") in self.last_weight:
                if abs(v - self.last_weight[msg["patient_id"]]) > rule["max_change_per_day"]:
                    reasons.append("implausible_jump:weight_kg")
        rp = self.cfg["replay"]
        try:
            ts = datetime.fromisoformat(msg["ts"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if now - ts > timedelta(hours=rp["max_age_hours"]):
                reasons.append("stale_timestamp")
            if ts - now > timedelta(minutes=rp["max_future_minutes"]):
                reasons.append("future_timestamp")
        except (KeyError, ValueError):
            reasons.append("missing_timestamp")
        nonce = msg.get("nonce")
        if rp["nonce_required"] and not nonce:
            reasons.append("missing_nonce")
        elif (msg.get("device_id"), nonce) in self.seen_nonces:
            reasons.append("replayed_nonce")
        key = self.device_keys.get(msg.get("device_id", ""))
        if key is not None and self.cfg["signature"]["required_if_registered"]:
            if not msg.get("signature") or not crypto.verify(key, self.signed_body(msg), msg["signature"]):
                reasons.append("bad_signature")
        return not reasons, reasons

    def ingest(self, msg: dict, now: datetime | None = None) -> dict:
        ok, reasons = self.check(msg, now)
        if ok:
            self.seen_nonces.add((msg.get("device_id"), msg.get("nonce")))
            if "weight_kg" in msg.get("readings", {}):
                self.last_weight[msg["patient_id"]] = float(msg["readings"]["weight_kg"])
        if self.audit is not None:
            self.audit.append("device_reading_accepted" if ok else "device_reading_rejected", actor=msg.get(
                "device_id", "unknown_device"), subject=msg.get("patient_id"), reasons=reasons)
        return {"accepted": ok, "reasons": reasons}
