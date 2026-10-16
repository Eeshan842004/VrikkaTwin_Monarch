"""HMAC-SHA256 hash-chained audit log with signed checkpoints (§21.2).

Each record carries the MAC of the previous record, so editing, deleting or reordering any record breaks ``verify()``.
The key comes from settings (``AUDIT_KEY`` in the environment / .env). Records are kept in memory and, if a path is
given, appended to a JSONL file. Signed checkpoints and the tamper demo are added in Part 6; this core is what the
red-flag screens already write to (Decisions v4 5a).
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from vrikka.config import settings

GENESIS = "0" * 64


def _canonical(record: dict) -> bytes:
    return json.dumps({k: v for k, v in record.items() if k != "mac"}, sort_keys=True, ensure_ascii=False,
                      default=str).encode("utf-8")


class AuditLog:
    def __init__(self, path: Path | None = None, key: str | None = None):
        self._key = (key if key is not None else settings().audit_key).encode("utf-8")
        self.path = path
        self.records: list[dict] = []
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

    def verify(self) -> bool:
        prev = GENESIS
        for i, rec in enumerate(self.records):
            if rec.get("seq") != i or rec.get("prev") != prev or not hmac.compare_digest(rec["mac"], self._mac(rec)):
                return False
            prev = rec["mac"]
        return True
