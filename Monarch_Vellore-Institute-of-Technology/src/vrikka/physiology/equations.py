"""Kidney equations: CKD-EPI 2021, KFRE, KDIGO staging, unit handling and baseline creatinine (master plan §9.3).

Golden values (tested): CKD-EPI F 60 y Cr 1.0 -> 64.5, M 50 y Cr 1.2 -> 73.7; KFRE M 65 y eGFR 35 UACR 300
non-North-American -> 2 y 0.0305, 5 y 0.1132.

The label and the twin's Monte-Carlo risk must read creatinine the same way (Decisions v1 item 5): one value per
day at ``creatinine_sample_hour`` (08:00), through :func:`kdigo_daily_stages`, with the baseline from
:func:`baseline_creatinine`.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from vrikka.config import param

# CKD-EPI 2021 (race-free) constants; part of the published equation, not tunable parameters.
_KAPPA = {True: 0.7, False: 0.9}
_ALPHA = {True: -0.241, False: -0.302}


def egfr_ckd_epi_2021(scr_mg_dl, age, female):
    """eGFR (mL/min/1.73 m2) from serum creatinine with the race-free CKD-EPI 2021 equation. Accepts arrays."""
    scr = np.asarray(scr_mg_dl, dtype=float)
    fem = np.asarray(female, dtype=bool)
    kappa = np.where(fem, 0.7, 0.9)
    alpha = np.where(fem, -0.241, -0.302)
    r = scr / kappa
    e = 142.0 * np.minimum(r, 1.0) ** alpha * np.maximum(r, 1.0) ** -1.200 * 0.9938 ** np.asarray(age, dtype=float)
    out = np.where(fem, e * 1.012, e)
    return float(out) if out.ndim == 0 else out


def creatinine_from_egfr(egfr, age, female: bool) -> float:
    """Inverse of CKD-EPI 2021: the creatinine (mg/dL) that gives this eGFR for this age and sex."""
    k = egfr / (142.0 * 0.9938 ** age * (1.012 if female else 1.0))
    alpha = _ALPHA[bool(female)]
    r = k ** (1.0 / alpha) if k >= 1.0 else k ** (-1.0 / 1.200)
    return float(r * _KAPPA[bool(female)])


def kfre_4var(age: float, male: bool, egfr: float, uacr_mg_g: float, years: int = 2,
              north_american: bool = False) -> float:
    """4-variable Kidney Failure Risk Equation (Tangri). Only meaningful for eGFR 10-59 with a known UACR."""
    lp = (-0.2201 * (age / 10 - 7.036) + 0.2467 * (int(male) - 0.5642)
          - 0.5567 * (egfr / 5 - 7.222) + 0.4510 * (math.log(uacr_mg_g) - 5.137))
    region = "na" if north_american else "non_na"
    s0 = param(f"kfre_s0_{years}y_{region}")
    return 1.0 - s0 ** math.exp(lp)


def kfre_is_valid(egfr: float, uacr_mg_g: float | None) -> bool:
    return uacr_mg_g is not None and param("kfre_valid_egfr_min") <= egfr <= param("kfre_valid_egfr_max")


def creatinine_to_mg_dl(value: float) -> tuple[float, bool]:
    """Normalise a lab creatinine to mg/dL. Values above the registry threshold are treated as umol/L.

    Returns (mg/dL, converted?). Example: 88 -> (0.995, True).
    """
    if value > param("creatinine_umol_detect_threshold"):
        return value / param("creatinine_umol_per_mg_dl"), True
    return float(value), False


def uacr_to_mg_g(value: float, unit: str = "mg/g") -> float:
    return value * param("uacr_mg_g_per_mg_mmol") if unit == "mg/mmol" else float(value)


def kdigo_stage(times_h: np.ndarray, cr: np.ndarray, i: int, baseline: float | None = None) -> int:
    """KDIGO creatinine criteria at index ``i``.

    AKI must be present (rise >= 0.3 mg/dL within 48 h, or >= 1.5x baseline / 7-day low) before staging; the
    Cr >= 4.0 rule only upgrades an existing AKI to stage 3 (matches mimic-code ``kdigo_stages.sql``). A stable
    CKD patient with Cr 4.2 is not AKI.
    """
    times_h, cr = np.asarray(times_h, dtype=float), np.asarray(cr, dtype=float)
    t, c = times_h[i], cr[i]
    w48 = cr[(times_h >= t - 48) & (times_h < t)]
    w7d = cr[(times_h >= t - 168) & (times_h < t)]
    base = baseline if baseline is not None else (w7d.min() if w7d.size else c)
    ratio = c / base if base > 0 else 1.0
    aki = ratio >= 1.5 or (w48.size > 0 and c - w48.min() >= 0.3)
    if not aki:
        return 0
    if ratio >= 3.0 or c >= 4.0:
        return 3
    if ratio >= 2.0:
        return 2
    return 1


def daily_samples(times_h: np.ndarray, cr: np.ndarray, hour: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Pick one creatinine per day at ``hour`` (default registry ``creatinine_sample_hour`` = 08:00).

    ``times_h`` are hours since local midnight of day 0, e.g. from an hourly simulation. Only these daily values
    may feed KDIGO for labels and for the twin's risk (Decisions v1 item 5).
    """
    hour = int(param("creatinine_sample_hour")) if hour is None else hour
    times_h, cr = np.asarray(times_h, dtype=float), np.asarray(cr, dtype=float)
    mask = np.isclose(np.mod(times_h, 24.0), hour)
    return times_h[mask], cr[mask]


def kdigo_daily_stages(times_h: np.ndarray, cr: np.ndarray, baseline: float | None = None,
                       hour: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """KDIGO stage for every daily 08:00 sample. Returns (sample times in hours, stages)."""
    td, cd = daily_samples(times_h, cr, hour)
    stages = np.array([kdigo_stage(td, cd, i, baseline) for i in range(len(cd))], dtype=int)
    return td, stages


def baseline_creatinine(labs: Sequence[tuple[float, float]], now_day: float, age: float, female: bool,
                        stable: Sequence[bool] | None = None) -> tuple[float, str]:
    """Outpatient baseline creatinine (master plan §9.3).

    ``labs`` = [(day, creatinine mg/dL), ...]. Rule: the mean of the last 2 stable values within 365 days; if only
    one exists, use it; if none, back-calculate from the registry fallback eGFR (75) and flag it.
    Returns (baseline mg/dL, source) with source in {"mean_last_2", "single", "back_calculated"}.
    """
    stable = [True] * len(labs) if stable is None else list(stable)
    recent = [(d, v) for (d, v), ok in zip(labs, stable, strict=True) if ok and now_day - 365 <= d <= now_day]
    recent.sort()
    if len(recent) >= 2:
        return float(np.mean([v for _, v in recent[-2:]])), "mean_last_2"
    if len(recent) == 1:
        return float(recent[0][1]), "single"
    return creatinine_from_egfr(param("baseline_egfr_fallback"), age, female), "back_calculated"
