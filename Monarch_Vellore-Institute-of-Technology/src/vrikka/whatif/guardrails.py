"""Hard-coded clinical guardrails (§14.2, §38; Decisions v4 5b, 5c; Part 5). Thresholds live in config/guardrails.yaml
and the registry; this module only applies them.

- ORS: with heart failure, eGFR < 30, or a last potassium >= 5.5 mmol/L the ORS lever and the "drink ORS" advice become
  "Fluid type and amount as advised by your doctor", with a caution badge and the reason(s). WHO reduced-osmolarity
  ORS carries 75 mmol/L sodium and 20 mmol/L potassium, which is why these patients need individual advice.
- Paracetamol: the daily total across brands (Combiflam carries 325 mg) is checked against the ceiling (4 g; 3 g at
  age >= 65, weight < 50 kg, liver disease or alcohol use).
- Potassium: >= 5.5 mmol/L puts a caution on every lever; >= 6.0 always means a same-day repeat and a clinician alert.
- Heart failure + pausing a diuretic: warning, clinician decides.
- Co-trimoxazole / trimethoprim (creatinine-secretion inhibitors): an AKI flag is never suppressed.
- Exclusions: age < 18, pregnancy, eGFR < 15 or dialysis -> no risk is computed.
"""
from __future__ import annotations

from collections.abc import Iterable

from vrikka.config import load_yaml, param
from vrikka.physiology.pk_nsaid import paracetamol_mg_per_day


def _cfg() -> dict:
    return load_yaml("guardrails")


def drug_classes(generics: Iterable[str]) -> set[str]:
    lex = load_yaml("drugs_india")["generics"]
    return {lex[g] for g in generics if g in lex}


def ors_guardrail(heart_failure: bool, egfr: float | None, last_potassium: float | None) -> dict:
    """Whether the ORS lever / advice is offered as is, and the i18n keys to show."""
    c = _cfg()["ors"]
    rule = c["caution_if"]
    reasons = []
    if heart_failure and rule["heart_failure"]:
        reasons.append("heart_failure")
    if egfr is not None and egfr < rule["egfr_below"]:
        reasons.append("egfr_lt_30")
    if last_potassium is not None and last_potassium >= rule["last_potassium_at_or_above"]:
        reasons.append("k_ge_5_5")
    return {
        "ors_lever_allowed": not reasons,
        "advice_key": "ors.doctor_advises" if reasons else "ors.drink",
        "badge_key": c["caution_badge_key"] if reasons else c["evidence_badge_key"],
        "reason_keys": [f"ors.reason.{r}" for r in reasons],
    }


def paracetamol_ceiling_mg(age: float, weight_kg: float, liver_disease: bool = False,
                           alcohol_use: bool = False) -> float:
    hr = _cfg()["paracetamol"]["high_risk_if"]
    high = (age >= hr["age_at_or_above"] or weight_kg < hr["weight_below_kg"]
            or (liver_disease and hr["liver_disease"]) or (alcohol_use and hr["alcohol_use"]))
    return 1000.0 * param("paracetamol_ceiling_high_risk_g_day" if high else "paracetamol_ceiling_g_day")


def paracetamol_check(tablets: dict[str, float], age: float, weight_kg: float, liver_disease: bool = False,
                      alcohol_use: bool = False) -> dict:
    """Daily paracetamol total across brands (brand -> tablets per day) against the personal ceiling."""
    c = _cfg()["paracetamol"]
    total = paracetamol_mg_per_day(tablets)
    ceiling = paracetamol_ceiling_mg(age, weight_kg, liver_disease, alcohol_use)
    return {"total_mg": total, "ceiling_mg": ceiling, "within_ceiling": total <= ceiling,
            "near_ceiling": total >= c["near_ceiling_fraction"] * ceiling,
            "message_key": None if total <= ceiling else c["over_ceiling_key"]}


def potassium_rule(last_potassium: float | None) -> dict:
    """Same-day repeat + clinician alert at >= 6.0 mmol/L (always); caution on every lever at >= 5.5."""
    c = _cfg()["potassium"]
    if last_potassium is None:
        return {"level": None, "actions": [], "message_key": None, "caution_on_levers": False}
    if last_potassium >= param("potassium_alert_mmol_l"):
        return {"level": "alert", "actions": list(c["alert_actions"]), "message_key": c["alert_key"],
                "caution_on_levers": True}
    if last_potassium >= param("potassium_caution_mmol_l"):
        return {"level": "caution", "actions": [], "message_key": c["caution_key"], "caution_on_levers": True}
    return {"level": None, "actions": [], "message_key": None, "caution_on_levers": False}


def pause_warnings(paused_classes: Iterable[str], heart_failure: bool) -> list[str]:
    """Warnings attached to drug-pause levers (heart failure + pausing a diuretic -> fluid overload risk)."""
    w = _cfg()["pause_warnings"]["heart_failure_diuretic"]
    return [w["message_key"]] if heart_failure and set(paused_classes) & set(w["classes"]) else []


def aki_flag_with_secretion_inhibitor(aki_flag: bool, generics: Iterable[str]) -> dict:
    """Co-trimoxazole never suppresses AKI: the flag is returned unchanged, with a note if the drug is present."""
    c = _cfg()["creatinine_secretion_inhibitors"]
    present = bool(drug_classes(generics) & set(c["classes"]))
    return {"aki_flag": aki_flag, "note_key": c["message_key"] if present else None,
            "check_potassium": present}


def exclusion_check(age: float, pregnant: bool = False, egfr: float | None = None, dialysis: bool = False) -> dict:
    """People VrikkaTwin is not designed for: no risk is computed and the screen gives the reason(s)."""
    c = _cfg()["exclusions"]
    reasons = []
    if age < c["min_age_years"]:
        reasons.append("exclude.under_18")
    if pregnant and c["pregnancy"]:
        reasons.append("exclude.pregnancy")
    if (egfr is not None and egfr < c["egfr_below"]) or (dialysis and c["dialysis"]):
        reasons.append("exclude.egfr_lt_15_or_dialysis")
    return {"excluded": bool(reasons), "reason_keys": reasons}
