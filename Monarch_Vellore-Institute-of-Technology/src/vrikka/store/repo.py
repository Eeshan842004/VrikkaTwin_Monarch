"""Repository functions over the SQLite store (tasks and check-ins). The services layer is the only caller."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from vrikka.security.crypto import decrypt_text, encrypt_text


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def add_task(con: sqlite3.Connection, patient_id: str, ordered_by: str, reason: str = "",
             kind: str = "home_kidney_test") -> int:
    cur = con.execute("INSERT INTO tasks (patient_id, kind, status, ordered_by, ordered_at, reason) "
                      "VALUES (?, ?, 'ordered', ?, ?, ?)", (patient_id, kind, ordered_by, _now(), reason))
    con.commit()
    return int(cur.lastrowid)


def tasks(con: sqlite3.Connection, patient_id: str | None = None, status: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM tasks WHERE 1=1", []
    if patient_id:
        q, args = q + " AND patient_id = ?", [*args, patient_id]
    if status:
        q, args = q + " AND status = ?", [*args, status]
    return [dict(r) for r in con.execute(q + " ORDER BY task_id DESC", args)]


def record_result(con: sqlite3.Connection, task_id: int, creatinine: float | None, potassium: float | None,
                  resulted_by: str, flag: str) -> None:
    con.execute("UPDATE tasks SET status='resulted', creatinine_mg_dl=?, potassium_mmol_l=?, resulted_by=?, "
                "resulted_at=?, result_flag=? WHERE task_id=?",
                (creatinine, potassium, resulted_by, _now(), flag, task_id))
    con.commit()


def add_checkin(con: sqlite3.Connection, patient_id: str, actor: str, role: str, language: str, fields: dict,
                text: str | None, red_flag: str) -> int:
    clean = {k: (None if isinstance(v, float) and v == float("inf") else v) for k, v in fields.items()}
    cur = con.execute("INSERT INTO checkins (patient_id, actor, role, ts, language, fields_json, text_enc, red_flag) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (patient_id, actor, role, _now(), language, json.dumps(clean, default=str),
                       encrypt_text(text) if text else None, red_flag))
    con.commit()
    return int(cur.lastrowid)


def checkins(con: sqlite3.Connection, patient_id: str) -> list[dict]:
    out = []
    for r in con.execute("SELECT * FROM checkins WHERE patient_id = ? ORDER BY checkin_id DESC", (patient_id,)):
        d = dict(r)
        d["fields"] = json.loads(d.pop("fields_json"))
        enc = d.pop("text_enc")
        d["text"] = decrypt_text(enc) if enc else None
        out.append(d)
    return out
