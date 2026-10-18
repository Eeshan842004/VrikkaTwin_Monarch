"""Record shapes shared by the services layer and the API (plain dataclasses; the store is sqlite3)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LabResult:
    task_id: int
    creatinine_mg_dl: float | None
    potassium_mmol_l: float | None


@dataclass(frozen=True)
class CheckinRequest:
    patient_id: str
    language: str = "en"
    fields: dict | None = None          # structured capture fields (config/red_flags.yaml capture_fields)
    text: str | None = None             # free-text check-in (parsed with whatif.red_flags.parse_text)
