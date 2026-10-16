"""Heat-illness and kidney red flags (Decisions v4 5a; config/red_flags.yaml). They run BEFORE any risk model.

- EMERGENCY (possible heatstroke: confusion, fainting, seizure, unresponsiveness, or temperature >= 40 degC; NCDC
  heat action plan): an emergency screen ("Call 108 / 112 now ..."), and NO kidney-injury risk is computed or shown.
- URGENT (no urine for 12 h; dark cola-coloured urine with muscle pain after heat or heavy work; vomiting that stops
  fluids staying down for more than 6 h): a same-day doctor message; the risk is still shown to the clinician but the
  alert level is at least red.
Every fired flag is written to the audit log. Messages come from config/i18n/<lang>.yaml (EN / HI / KN / TE).
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from vrikka.config import load_yaml

LANGUAGES = ("en", "hi", "kn", "te")
LEVEL_ORDER = {"none": 0, "urgent": 1, "emergency": 2}
# lexicon entry -> check-in field it sets (text check-in)
TEXT_SIGNS = {
    "confusion": "confusion",
    "fainting": "fainting",
    "seizure": "seizure",
    "unresponsive": "unresponsive",
    "no_urine": "no_urine_hours",
    "dark_cola_urine": "dark_cola_urine",
    "muscle_pain": "muscle_pain",
    "cannot_keep_fluids": "vomiting_cannot_keep_fluids_hours",
}
_TEMP = re.compile(r"(\d{2,3}(?:\.\d+)?)\s*(?:°|deg(?:ree)?s?)?\s*([cf])\b", re.I)
_HOURS = re.compile(r"(\d{1,2})\s*(?:h|hr|hrs|hour|hours|ghante|ghanta|घंटे|ಗಂಟೆ|గంటల|గంటలు)", re.I)


def messages(lang: str) -> dict[str, str]:
    if lang not in LANGUAGES:
        raise ValueError(f"unsupported language '{lang}' (supported: {LANGUAGES})")
    return load_yaml(f"i18n/{lang}")


@dataclass
class RedFlagResult:
    level: str                                  # none / urgent / emergency
    flags: list[str] = field(default_factory=list)
    show_risk: bool = True
    title: str = ""
    body: str = ""
    call: str | None = None
    notes: list[str] = field(default_factory=list)
    duration_assumed: list[str] = field(default_factory=list)


def _sign_present(name: str, spec: dict | None, checkin: dict) -> bool:
    if spec is None:                            # boolean sign
        return bool(checkin.get(name))
    if "all_of" in spec:
        return all(bool(checkin.get(s)) for s in spec["all_of"])
    v = checkin.get(spec["field"])
    return v is not None and v is not False and float(v) >= float(spec["at_least"])


def evaluate(checkin: dict, lang: str = "en", audit=None, patient_id: str | None = None,
             actor: str = "system") -> RedFlagResult:
    """Red flags for one check-in (dict of capture fields; see config/red_flags.yaml ``capture_fields``)."""
    cfg = load_yaml("red_flags")
    msg = messages(lang)
    fired = []
    for fid, f in cfg["flags"].items():
        if any(_sign_present(s, cfg["signs"].get(s), checkin) for s in f["any_of"]):
            fired.append(fid)
    if not fired:
        return RedFlagResult("none")
    top = max(fired, key=lambda fid: LEVEL_ORDER[cfg["flags"][fid]["level"]])
    f = cfg["flags"][top]
    key = f["message_key"]
    res = RedFlagResult(level=f["level"], flags=fired, show_risk=bool(f["show_risk"]) and f["level"] != "emergency",
                        title=msg[f"{key}.title"], body=msg[f"{key}.body"], call=f.get("call"))
    assumed = [k for k in checkin.get("_duration_assumed", []) if k]
    if assumed:
        res.duration_assumed = assumed
        res.notes.append(msg["redflag.duration_not_stated"])
    if audit is not None:
        audit.append("red_flag", actor=actor, subject=patient_id, level=res.level, flags=fired, language=lang,
                     risk_suppressed=not res.show_risk)
    return res


def parse_text(text: str, lang: str) -> dict:
    """Text check-in -> capture fields, using config/symptoms_lexicon.yaml (lower-case substring match).

    A stated sign without a duration is treated as meeting its duration rule (safety first); those fields are listed
    in ``_duration_assumed`` so the screen can say so.
    """
    lex = load_yaml("symptoms_lexicon")
    t = text.lower()
    out: dict[str, Any] = {"_duration_assumed": []}
    hours = _HOURS.search(t)
    for sign, fieldname in TEXT_SIGNS.items():
        terms = lex.get(sign, {}).get(lang, []) + lex.get(sign, {}).get("en", [])
        if any(str(term).lower() in t for term in terms):
            if fieldname.endswith("_hours"):
                if hours:
                    out[fieldname] = float(hours.group(1))
                else:
                    out[fieldname] = float("inf")
                    out["_duration_assumed"].append(fieldname)
            else:
                out[fieldname] = True
    m = _TEMP.search(t)
    if m:
        v, unit = float(m.group(1)), m.group(2).lower()
        out["temperature_c"] = (v - 32) * 5 / 9 if unit == "f" else v
    return out


def screen_then_risk(checkin: dict, risk_fn: Callable[[], float], lang: str = "en", audit=None,
                     patient_id: str | None = None) -> dict:
    """Run the red flags first; compute the kidney-injury risk only if the screen allows it."""
    rf = evaluate(checkin, lang, audit, patient_id)
    if not rf.show_risk:
        return {"screen": rf, "risk": None, "minimum_level": None}
    return {"screen": rf, "risk": risk_fn(), "minimum_level": "red" if rf.level == "urgent" else None}
