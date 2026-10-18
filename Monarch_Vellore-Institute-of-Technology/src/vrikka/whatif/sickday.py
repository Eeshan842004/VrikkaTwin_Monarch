"""Sick-day guidance (Decisions v1: "sick-day guidance", not "sick-day rules"; Think Kidneys 2018).

When the patient reports an illness that dries the body out (fever, vomiting, diarrhoea, poor intake), the guidance
lists, for each relevant medicine the patient takes (generic name first), the reason a temporary pause is often
discussed, and ALWAYS routes the decision to the clinician: patient text never says "stop your medicine".
Painkillers: NSAIDs block the kidney's self-protection; paracetamol within its daily ceiling is usually the safer
choice. ORS advice goes through the ORS guardrail. Red flags always run first (whatif/red_flags.py).
"""
from __future__ import annotations

from collections.abc import Iterable

from vrikka.config import load_yaml
from vrikka.whatif.guardrails import ors_guardrail

ILLNESS_FIELDS = ("fever_excess_c", "vomit_episodes", "diarrhoea_episodes", "poor_intake")


def is_sick_day(report: dict) -> bool:
    return any(bool(report.get(f)) and float(report.get(f) or 0) > 0 for f in ILLNESS_FIELDS)


def guidance(generics: Iterable[str], report: dict, heart_failure: bool = False, egfr: float | None = None,
             last_potassium: float | None = None) -> dict:
    """Sick-day guidance items as i18n keys + the medicine (generic) each item refers to.

    Returns {"sick_day": bool, "items": [{"key", "generic", "class", "reason_key"}], "ors": guardrail dict}.
    """
    lex = load_yaml("drugs_india")
    reasons = lex["pause_reason"]
    gen_cls = lex["generics"]
    sick = is_sick_day(report)
    items = []
    if sick:
        seen = set()
        for g in generics:
            cls = gen_cls.get(g)
            if cls in reasons and g not in seen:
                seen.add(g)
                key = "sickday.painkiller" if cls.startswith("nsaid") else "sickday.ask_pause"
                items.append({"key": key, "generic": g, "class": cls, "reason_key": f"pause_reason.{cls}"})
        items.append({"key": "sickday.keep_others", "generic": None, "class": None, "reason_key": None})
    ors = ors_guardrail(heart_failure, egfr, last_potassium)
    return {"sick_day": sick, "items": items, "ors": ors}
