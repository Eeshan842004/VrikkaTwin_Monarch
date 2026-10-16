"""Display rules for every number shown to a doctor, patient or juror (Decisions v4 4b, 4d, 5c; config/guardrails.yaml).

- A risk is never shown as "0 %": below 1 % it reads "<1%" (200 Monte-Carlo draws cannot resolve less than 0.5 %), and a
  Monte-Carlo risk always carries its 95 % Wilson interval.
- A lab eGFR taken while creatinine is changing (>= 0.3 mg/dL from the last stable value, or a twin AKI flag) is tagged
  "not reliable while creatinine is changing"; CKD-EPI assumes steady state. The twin shows "modelled filtration
  (% of personal baseline, twin estimate)" instead.
"""
from __future__ import annotations

import math

from vrikka.config import load_yaml


def wilson_interval(p: float, n: int, z: float = 1.959964) -> tuple[float, float]:
    """95 % Wilson score interval for a proportion p estimated from n Monte-Carlo draws."""
    if n <= 0:
        return 0.0, 1.0
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, min(centre - half, p)), min(1.0, max(centre + half, p))


def pct_text(p: float) -> str:
    floor = load_yaml("guardrails")["risk_display"]["floor_text_below"]
    return "<1%" if p < floor else f"{round(100 * p):d}%"


def risk_text(p: float, n_draws: int | None = None) -> dict:
    """Text for a risk value. With ``n_draws`` (Monte-Carlo risk) the 95 % interval is added."""
    out = {"value": p, "text": pct_text(p)}
    if n_draws:
        lo, hi = wilson_interval(p, n_draws)
        out["interval"] = (lo, hi)
        out["text"] += f" (95% interval {pct_text(lo)}-{pct_text(hi)})" if hi >= 0.01 else ""
    return out


def lab_egfr_status(cr_lab: float, last_stable_cr: float | None, twin_aki_flag: bool = False) -> dict:
    """Whether a lab eGFR can be shown as a steady-state value, and the i18n tag if not."""
    delta = load_yaml("guardrails")["egfr_during_aki"]["changing_if_delta_mg_dl"]
    changing = twin_aki_flag or (last_stable_cr is not None and abs(cr_lab - last_stable_cr) >= delta)
    return {"reliable": not changing, "tag_key": "egfr.not_reliable" if changing else None,
            "use_in_slow_clock": not changing}


def modelled_filtration(gfr_frac: float) -> dict:
    """Twin-estimated filtration as % of the personal baseline (label key ``filtration.label``)."""
    return {"value_pct": round(100 * gfr_frac), "label_key": "filtration.label"}
