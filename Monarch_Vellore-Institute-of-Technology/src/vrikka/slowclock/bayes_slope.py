"""Bayesian eGFR slope: the slow clock's personal trajectory (master plan §13; Amendment 1 A1.9).

Model: eGFR_i = a + b x t_i + e_i, e_i ~ N(0, egfr_obs_sd^2), with t in years relative to "now" (past values have
t < 0), so a is today's underlying eGFR and b the yearly slope. Conjugate normal prior (a, b) ~ N(m0, P0):
- a: centred on the most recent stable eGFR (or the baseline eGFR if there is no lab), SD ``slope_intercept_sd``;
- b: the group prior from the registry, SD ``slope_prior_sd``:
  diabetes + albuminuria (UACR >= ``albuminuria_uacr_mg_g``) -> ``slope_prior_dkd_albuminuria`` (Trichy cohort),
  diabetes (with or without hypertension)                    -> ``slope_prior_dm_htn``,
  no diabetes                                                -> ``slope_prior_htn_no_dm``.
Posterior precision = P0^-1 + X'X / sigma^2; posterior mean = cov x (P0^-1 m0 + X'y / sigma^2).

Only STABLE eGFR values enter the slope (``fastclock.display.lab_egfr_status``): a value taken while creatinine is
changing (>= 0.3 mg/dL from the last stable value) is CKD-EPI outside steady state and is skipped (Decisions v4 5c).
Outputs are always shown as ranges (projection.py), never a single number.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from vrikka.config import param
from vrikka.fastclock.display import lab_egfr_status
from vrikka.physiology.equations import egfr_ckd_epi_2021

PRIOR_KEYS = {"dkd_albuminuria": "slope_prior_dkd_albuminuria", "dm_htn": "slope_prior_dm_htn",
              "htn_no_dm": "slope_prior_htn_no_dm"}


@dataclass
class SlopePosterior:
    mean: np.ndarray            # [a (eGFR now), b (slope per year)]
    cov: np.ndarray             # 2 x 2
    group: str                  # prior group (PRIOR_KEYS)
    n_obs: int                  # stable eGFR values used
    skipped: int                # values skipped because creatinine was changing

    @property
    def slope(self) -> float:
        return float(self.mean[1])

    @property
    def slope_sd(self) -> float:
        return float(np.sqrt(self.cov[1, 1]))

    def slope_range(self) -> tuple[float, float]:
        """10-90 % range of the yearly slope (normal posterior)."""
        from scipy.stats import norm

        lo, hi = param("slow_band_low_q"), param("slow_band_high_q")
        return (float(norm.ppf(lo, self.mean[1], self.slope_sd)), float(norm.ppf(hi, self.mean[1], self.slope_sd)))


def prior_group(dm: bool, uacr_mg_g: float | None = None) -> str:
    """Which registry slope prior applies (diabetes / albuminuria). Hypertension alone uses the no-diabetes prior."""
    if dm and uacr_mg_g is not None and uacr_mg_g >= param("albuminuria_uacr_mg_g"):
        return "dkd_albuminuria"
    return "dm_htn" if dm else "htn_no_dm"


def prior(egfr_now: float, group: str) -> tuple[np.ndarray, np.ndarray]:
    m0 = np.array([float(egfr_now), param(PRIOR_KEYS[group])])
    p0 = np.diag([param("slope_intercept_sd") ** 2, param("slope_prior_sd") ** 2])
    return m0, p0


def stable_egfr_series(labs: Sequence[tuple[float, float]], age_now: float, female: bool) -> tuple[list, int]:
    """[(t_years, creatinine mg/dL), ...] (t <= 0, oldest first) -> stable [(t_years, eGFR)] and the skipped count.

    eGFR uses the age at the time of the test. A value is stable unless it differs from the last stable creatinine
    by the display rule's delta (the first value is taken as stable).
    """
    out, skipped, last_stable = [], 0, None
    for t, cr in sorted(labs):
        if not lab_egfr_status(cr, last_stable)["use_in_slow_clock"]:
            skipped += 1
            continue
        last_stable = cr
        out.append((float(t), float(egfr_ckd_epi_2021(cr, age_now + t, female))))
    return out, skipped


def fit(egfr_obs: Sequence[tuple[float, float]], egfr_now: float, dm: bool, uacr_mg_g: float | None = None,
        skipped: int = 0) -> SlopePosterior:
    """Conjugate posterior of (eGFR now, slope) from stable [(t_years, eGFR)] observations (may be empty)."""
    group = prior_group(dm, uacr_mg_g)
    m0, p0 = prior(egfr_now, group)
    lam0 = np.linalg.inv(p0)
    if not egfr_obs:
        return SlopePosterior(m0, p0, group, 0, skipped)
    t = np.array([o[0] for o in egfr_obs], dtype=float)
    y = np.array([o[1] for o in egfr_obs], dtype=float)
    X = np.column_stack([np.ones_like(t), t])
    s2 = param("egfr_obs_sd") ** 2
    lam = lam0 + X.T @ X / s2
    cov = np.linalg.inv(lam)
    mean = cov @ (lam0 @ m0 + X.T @ y / s2)
    return SlopePosterior(mean, 0.5 * (cov + cov.T), group, len(egfr_obs), skipped)


def fit_from_labs(labs: Sequence[tuple[float, float]], age_now: float, female: bool, dm: bool,
                  uacr_mg_g: float | None = None, egfr_fallback: float | None = None) -> SlopePosterior:
    """Convenience: creatinine history -> stable eGFR series -> posterior. The intercept prior is centred on the
    latest stable eGFR, else ``egfr_fallback`` (e.g. the EHR baseline eGFR)."""
    obs, skipped = stable_egfr_series(labs, age_now, female)
    if obs:
        egfr_now = obs[-1][1]
    elif egfr_fallback is not None:
        egfr_now = egfr_fallback
    else:
        raise ValueError("no stable eGFR and no fallback eGFR")
    return fit(obs, egfr_now, dm, uacr_mg_g, skipped)
