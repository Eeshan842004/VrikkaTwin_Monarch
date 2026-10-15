"""Measurement models of the personal twin (master plan §10.1; Decisions v2 A-5a).

At 08:00 each day:
- morning weight      z_w   = w_dry - v_tot                                  (sigma_weight_kg)
- resting heart rate  z_hr  = HR_base + k_hr x v_ecf + hr_fever x fever_excess  (sigma_hr_bpm; beta-blocker:
                              k_hr x k_hr_beta_blocker_mult, sigma x sigma_hr_beta_blocker_mult)
- home systolic BP    z_bp  = SBP_base - k_bp x v_ecf                         (sigma_sbp_mmhg; optional, tier T2)
Fever sits inside the HR model so a febrile HR rise is not read as dehydration.
"""
from __future__ import annotations

import numpy as np

from vrikka.config import param

CHANNELS = ("weight", "hr", "sbp")


def noise_sd(beta_blocker: bool) -> np.ndarray:
    hr = param("sigma_hr_bpm") * (param("sigma_hr_beta_blocker_mult") if beta_blocker else 1.0)
    return np.array([param("sigma_weight_kg"), hr, param("sigma_sbp_mmhg")])


def hr_gain(beta_blocker: bool) -> float:
    return param("k_hr") * (param("k_hr_beta_blocker_mult") if beta_blocker else 1.0)


def hx(x: np.ndarray, hr_base: float, sbp_base: float, beta_blocker: bool, fever_excess_c: float = 0.0) -> np.ndarray:
    """Expected [weight, resting HR, SBP] for state(s) x = [v_tot, v_ecf, cr, log_theta, w_dry] (rows)."""
    x = np.atleast_2d(x)
    weight = x[:, 4] - x[:, 0]
    hr = hr_base + hr_gain(beta_blocker) * x[:, 1] + param("hr_fever_bpm_per_c") * max(fever_excess_c, 0.0)
    sbp = sbp_base - param("k_bp") * x[:, 1]
    return np.column_stack([weight, hr, sbp])
