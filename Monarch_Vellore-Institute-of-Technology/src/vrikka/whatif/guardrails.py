"""Hard-coded clinical guardrails (§14.2, §38; Decisions v4 5b, 5c). Thresholds live in config/guardrails.yaml.

ORS guardrail: with heart failure, eGFR < 30, or a last potassium >= 5.5 mmol/L the ORS lever and the "drink ORS" advice
become "Fluid type and amount as advised by your doctor", with a caution badge and the reason(s). WHO reduced-
osmolarity ORS carries 75 mmol/L sodium and 20 mmol/L potassium, which is why these patients need individual advice.
"""
from __future__ import annotations

from vrikka.config import load_yaml


def ors_guardrail(heart_failure: bool, egfr: float | None, last_potassium: float | None) -> dict:
    """Whether the ORS lever / advice is offered as is, and the i18n keys to show."""
    c = load_yaml("guardrails")["ors"]
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
