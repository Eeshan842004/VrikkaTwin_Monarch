"""HMAC-SHA256 hash-chained audit log with signed checkpoints (§21.2; Part 6).

Each record carries the MAC of the previous record, so editing, deleting or reordering any record breaks ``verify()``.
The key comes from settings (``AUDIT_KEY`` in the environment / .env). Records are kept in memory and, if a path is
given, appended to a JSONL file.

Signed checkpoints: ``checkpoint()`` signs (count, head MAC, time) with an Ed25519 key that is separate from the HMAC
key. Someone who learns the HMAC key could rebuild a forged chain, but could not re-sign the checkpoints, so
``verify_checkpoints()`` still catches it. ``first_bad_index()`` says where a chain breaks, and ``tamper_demo()``
shows the whole story for the Trust Center page.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vrikka.config import settings
from vrikka.security import crypto

GENESIS = "0" * 64


def _canonical(record: dict) -> bytes:
    return json.dumps({k: v for k, v in record.items() if k != "mac"}, sort_keys=True, ensure_ascii=False,
                      default=str).encode("utf-8")


class AuditLog:
    def __init__(self, path: Path | None = None, key: str | None = None, signing_key=None):
        self._key = (key if key is not None else settings().audit_key).encode("utf-8")
        self.path = path
        self.records: list[dict] = []
        self.checkpoints: list[dict] = []
        self._signer = signing_key or crypto.new_signing_key()
        self.public_key = crypto.public_key_b64(self._signer)
        if path is not None and path.exists():
            self.records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def _mac(self, record: dict) -> str:
        return hmac.new(self._key, _canonical(record), hashlib.sha256).hexdigest()

    def append(self, action: str, actor: str = "system", subject: str | None = None, **details: Any) -> dict:
        rec = {
            "seq": len(self.records),
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "actor": actor,
            "action": action,
            "subject": subject,
            "details": details,
            "prev": self.records[-1]["mac"] if self.records else GENESIS,
        }
        rec["mac"] = self._mac(rec)
        self.records.append(rec)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        return rec

    def first_bad_index(self) -> int | None:
        """Index of the first record whose sequence, back-link or MAC does not check out (None = intact)."""
        prev = GENESIS
        for i, rec in enumerate(self.records):
            if rec.get("seq") != i or rec.get("prev") != prev or not hmac.compare_digest(rec["mac"], self._mac(rec)):
                return i
            prev = rec["mac"]
        return None

    def verify(self) -> bool:
        return self.first_bad_index() is None

    # ------------------------------------------------------------------ signed checkpoints
    def checkpoint(self) -> dict:
        """Sign the current head of the chain (Ed25519, separate from the HMAC key)."""
        body = {"count": len(self.records), "head": self.records[-1]["mac"] if self.records else GENESIS,
                "ts": datetime.now(UTC).isoformat(timespec="seconds")}
        cp = {**body, "signature": crypto.sign(self._signer, body), "public_key": self.public_key}
        self.checkpoints.append(cp)
        return cp

    def verify_checkpoints(self, public_key: str | None = None) -> dict:
        """Every checkpoint's signature is valid and the chain still has the signed head at the signed position."""
        pub = public_key or self.public_key
        bad = []
        for k, cp in enumerate(self.checkpoints):
            body = {x: cp[x] for x in ("count", "head", "ts")}
            ok_sig = crypto.verify(pub, body, cp["signature"])
            n = cp["count"]
            head_now = self.records[n - 1]["mac"] if 0 < n <= len(self.records) else (GENESIS if n == 0 else None)
            if not ok_sig or head_now != cp["head"]:
                bad.append({"checkpoint": k, "signature_ok": ok_sig, "head_matches": head_now == cp["head"]})
        return {"ok": not bad and self.verify(), "checkpoints": len(self.checkpoints), "problems": bad,
                "chain_intact": self.verify(), "first_bad_record": self.first_bad_index()}


def clone(log: AuditLog) -> AuditLog:
    """Independent copy of the records and checkpoints (same keys), for demos and tests."""
    c = AuditLog.__new__(AuditLog)
    c._key, c.path, c._signer, c.public_key = log._key, None, log._signer, log.public_key
    c.records, c.checkpoints = copy.deepcopy(log.records), copy.deepcopy(log.checkpoints)
    return c


def tamper_demo(n: int = 6, edit_index: int = 2) -> dict:
    """Trust Center demo: build a small log, sign a checkpoint, edit one record, then show what each check says.

    Also shows that re-computing every MAC with a stolen HMAC key (a "re-chained forgery") passes ``verify()`` but
    fails the signed checkpoint.
    """
    log = AuditLog(key="tamper-demo-key")
    for i in range(n):
        log.append("read_patient", actor="dr_demo", subject=f"P{i:03d}", purpose="care_management")
    log.checkpoint()
    before = log.verify_checkpoints()
    edited = clone(log)
    edited.records[edit_index]["subject"] = "P999"
    after_edit = edited.verify_checkpoints()
    forged = clone(edited)
    prev = forged.records[edit_index - 1]["mac"] if edit_index else GENESIS
    for rec in forged.records[edit_index:]:
        rec["prev"] = prev
        rec["mac"] = forged._mac(rec)
        prev = rec["mac"]
    after_forgery = forged.verify_checkpoints()
    return {"records": n, "edited_record": edit_index, "before": before, "after_edit": after_edit,
            "after_rechained_forgery": after_forgery}
