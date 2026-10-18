"""Kidney Failure Risk Equation for the slow-clock panel (master plan §9.3, §13).

The 4-variable KFRE (Tangri; non-North-American calibration by default, male centering as published) is shown ONLY
where it is valid: eGFR ``kfre_valid_egfr_min``-``kfre_valid_egfr_max`` with a known UACR. Elsewhere the panel says
why it is not shown instead of extrapolating. The UI words the outcome as "needing dialysis or a transplant" (the
equation's endpoint); it is a long-term outcome and is never used to describe the heat / sick-day episodes.
"""
from __future__ import annotations

from vrikka.config import param
from vrikka.physiology.equations import kfre_4var, kfre_is_valid


def kfre_panel(age: float, male: bool, egfr: float, uacr_mg_g: float | None, north_american: bool = False) -> dict:
    if uacr_mg_g is None or uacr_mg_g <= 0:
        return {"valid": False, "reason_key": "kfre.no_uacr"}
    if not kfre_is_valid(egfr, uacr_mg_g):
        key = "kfre.egfr_too_high" if egfr > param("kfre_valid_egfr_max") else "kfre.egfr_too_low"
        return {"valid": False, "reason_key": key}
    r2 = kfre_4var(age, male, egfr, uacr_mg_g, years=2, north_american=north_american)
    r5 = kfre_4var(age, male, egfr, uacr_mg_g, years=5, north_american=north_american)
    return {"valid": True, "risk_2y": r2, "risk_5y": r5, "referral_prompt": r5 >= param("kfre_referral_5y"),
            "referral_threshold_5y": param("kfre_referral_5y")}
