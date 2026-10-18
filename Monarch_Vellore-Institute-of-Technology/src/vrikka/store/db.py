"""SQLite store for the demo app (Part 6): kidney-test orders (tasks), lab results and check-ins. Standard-library
sqlite3; the file is data/app.db (gitignored) or ":memory:" for tests. Identifying free text is encrypted (Fernet)
before it is written.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from vrikka.config import DATA_DIR

DEFAULT_PATH = DATA_DIR / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  TEXT NOT NULL,
    kind        TEXT NOT NULL,              -- home_kidney_test
    status      TEXT NOT NULL,              -- ordered / sample_taken / resulted / cancelled
    ordered_by  TEXT NOT NULL,
    ordered_at  TEXT NOT NULL,
    reason      TEXT,
    creatinine_mg_dl REAL,
    potassium_mmol_l REAL,
    resulted_by TEXT,
    resulted_at TEXT,
    result_flag TEXT                        -- e.g. kdigo_stage_1 / no_aki / k_alert
);
CREATE TABLE IF NOT EXISTS checkins (
    checkin_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  TEXT NOT NULL,
    actor       TEXT NOT NULL,
    role        TEXT NOT NULL,
    ts          TEXT NOT NULL,
    language    TEXT NOT NULL,
    fields_json TEXT NOT NULL,
    text_enc    TEXT,                       -- free text, Fernet-encrypted
    red_flag    TEXT NOT NULL               -- none / urgent / emergency
);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    p = DEFAULT_PATH if path is None else path
    if p != ":memory:":
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con
