"""Slow-clock projection: eGFR ranges over the next years and years-to-threshold ranges (master plan §13; A1.9).

Draws (a, b) from the slope posterior (bayes_slope.py) and adds deterministic modifiers from the registry:

- AKI slope penalty (Decisions v5 C3; Amendment 2 A2.7): the Trichy figure is "intercurrent AKI (yes/no) ASSOCIATED
  with 1.83 mL/min/year excess eGFR loss" in one diabetic kidney disease cohort (n = 274). It is applied ONCE for any
  AKI; each extra episode adds ``aki_penalty_extra_episode_mult`` x the penalty (an ASSUMPTION), counting at most
  ``aki_penalty_max_episodes`` episodes. The penalty scales by stage (``aki_penalty_stage{1,2,3}_mult``) and fades:
  rate(s) = aki_slope_penalty x stage_mult x w x exp(-(s - t_aki) / aki_penalty_tau_years).
  For a past episode only the part of the fading penalty that is still to come (from now on) is added; the observed
  eGFR values already carry the past. For people without diabetes the figure is "extrapolated" (see ``wording``).
- One-off eGFR step at a FUTURE AKI (``aki_step_stage{1,2,3}``, incomplete recovery). Past steps are in the data.
- SGLT2 inhibitor started at t_s: an expected haemodynamic dip ``sglt2i_initial_dip`` (not injury), then a slower
  decline by ``sglt2i_slope_effect`` per year (EMPA-KIDNEY 1.37; an input, never described as reproduced).
- Blood-pressure control (``sbp_control_slope_effect_per_10mmhg``) and stopping a chronic NSAID
  (``stop_chronic_nsaid_slope_effect``): ASSUMPTIONS, labelled as such.

Uncertainty: (a, b) come from the posterior, and every modifier parameter above is drawn uniformly over its registered
range (``UNCERTAIN``), so the effect of an AKI or a treatment is itself a range.
Everything is reported as a 10-90 % range (``slow_band_low_q`` / ``slow_band_high_q``); a single "kidney-years"
number is never a headline. Years beyond ``projection_search_years`` read ">15 years".
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from vrikka.config import SEED, param, param_range
from vrikka.slowclock.bayes_slope import SlopePosterior

THRESHOLD_KEYS = {"g3a": "egfr_threshold_g3a", "g4": "egfr_threshold_g4", "g5": "egfr_threshold_g5"}


@dataclass(frozen=True)
class AkiEpisode:
    t_years: float              # relative to now: negative = in the past, positive = a hypothetical future episode
    stage: int = 1


@dataclass
class Scenario:
    """What the projection assumes from now on. Empty = the patient continues as they are."""

    episodes: Sequence[AkiEpisode] = ()
    sglt2i_start_years: float | None = None      # start an SGLT2 inhibitor at this time (None = no change)
    sbp_drop_mmhg: float = 0.0                   # systolic BP brought this much closer to target
    stop_chronic_nsaid: bool = False
    label: str = "continue as is"


@dataclass
class Projection:
    t_years: np.ndarray
    low: np.ndarray
    median: np.ndarray
    high: np.ndarray
    years_to: dict = field(default_factory=dict)  # threshold name -> {"threshold", "low", "median", "high", "text"}
    scenario: str = ""
    group: str = ""


def grid() -> np.ndarray:
    step = param("projection_step_years")
    return np.round(np.arange(0.0, param("projection_search_years") + step / 2, step), 6)


# Modifier parameters whose registry RANGE is propagated into the projection (uniform over the range), so the effect
# of an AKI or a treatment is itself a range, never a single number. The slope / intercept come from the posterior.
UNCERTAIN = ("aki_slope_penalty", "aki_penalty_tau_years", "aki_penalty_extra_episode_mult",
             "aki_penalty_stage1_mult", "aki_penalty_stage2_mult", "aki_penalty_stage3_mult",
             "aki_step_stage1", "aki_step_stage2", "aki_step_stage3", "sglt2i_initial_dip", "sglt2i_slope_effect",
             "sbp_control_slope_effect_per_10mmhg", "stop_chronic_nsaid_slope_effect")


def modifier_params(n: int | None = None, rng: np.random.Generator | None = None) -> dict:
    """Registry values (n None) or n uniform draws over each registered range, as (n, 1) arrays."""
    if n is None:
        return {k: param(k) for k in UNCERTAIN}
    out = {}
    for k in UNCERTAIN:
        lo, hi = param_range(k)
        out[k] = rng.uniform(lo, hi, size=(n, 1))
    return out


def aki_effect(t: np.ndarray, episodes: Sequence[AkiEpisode], include_steps: bool = True,
               p: dict | None = None) -> np.ndarray:
    """Additive eGFR change (mL/min/1.73 m2, <= 0) from AKI episodes on the time grid ``t`` (years from now).

    ``p`` = modifier parameters (scalars, or (n, 1) arrays for n draws); default = the registry values."""
    p = p or modifier_params()
    eff = np.zeros(np.broadcast_shapes(np.shape(p["aki_slope_penalty"]), t.shape), dtype=float)
    tau = p["aki_penalty_tau_years"]
    counted = sorted(episodes, key=lambda e: e.t_years)[: int(param("aki_penalty_max_episodes"))]
    for k, e in enumerate(counted):
        w = 1.0 if k == 0 else p["aki_penalty_extra_episode_mult"]
        mult = p[f"aki_penalty_stage{e.stage}_mult"]
        start = max(0.0, e.t_years)
        eff = eff + np.where(t > start, p["aki_slope_penalty"] * mult * w * tau
                             * (np.exp(-(start - e.t_years) / tau) - np.exp(-(t - e.t_years) / tau)), 0.0)
    if include_steps:
        for e in episodes:
            if e.t_years >= 0:
                eff = eff - np.where(t >= e.t_years, p[f"aki_step_stage{e.stage}"], 0.0)
    return eff


def treatment_effect(t: np.ndarray, sc: Scenario, p: dict | None = None) -> np.ndarray:
    p = p or modifier_params()
    eff = np.zeros(np.broadcast_shapes(np.shape(p["sglt2i_slope_effect"]), t.shape), dtype=float)
    if sc.sglt2i_start_years is not None:
        ts = sc.sglt2i_start_years
        eff = eff + np.where(t >= ts, -p["sglt2i_initial_dip"] + p["sglt2i_slope_effect"] * (t - ts), 0.0)
    if sc.sbp_drop_mmhg > 0:
        eff = eff + p["sbp_control_slope_effect_per_10mmhg"] * sc.sbp_drop_mmhg / 10.0 * t
    if sc.stop_chronic_nsaid:
        eff = eff + p["stop_chronic_nsaid_slope_effect"] * t
    return eff


def draws(post: SlopePosterior, sc: Scenario, n_draws: int | None = None, seed: int = SEED) -> tuple[np.ndarray,
                                                                                                    np.ndarray]:
    """eGFR draws (n, T) on the search grid for one scenario. Common random numbers: the same seed gives the same
    (a, b) and the same modifier-parameter draws, so scenario differences come from the scenario alone."""
    t = grid()
    n = int(n_draws or param("slow_mc_draws"))
    rng = np.random.default_rng(seed)
    ab = rng.multivariate_normal(post.mean, post.cov + 1e-12 * np.eye(2), size=n)
    p = modifier_params(n, rng)
    egfr = ab[:, :1] + ab[:, 1:] * t[None, :] + aki_effect(t, sc.episodes, p=p) + treatment_effect(t, sc, p)
    return t, np.maximum(egfr, 0.0)              # a straight-line extrapolation cannot go below zero filtration


def years_to_threshold(t: np.ndarray, egfr: np.ndarray, threshold: float) -> np.ndarray:
    """First grid time each draw is below ``threshold`` (0 if already below; inf if never within the search)."""
    below = egfr < threshold
    first = np.where(below.any(axis=1), t[np.argmax(below, axis=1)], np.inf)
    return first


def _years_text(lo: float, hi: float) -> str:
    cap = param("projection_search_years")

    def one(v: float) -> str:
        return f">{cap:g}" if not np.isfinite(v) else f"{v:.1f}".rstrip("0").rstrip(".")
    if hi == 0:
        return "already below"
    if not np.isfinite(lo):
        return f"more than {cap:g} years"
    return f"{one(lo)}-{one(hi)} years" if np.isfinite(hi) else f"{one(lo)} to more than {cap:g} years"


def project(post: SlopePosterior, sc: Scenario | None = None, n_draws: int | None = None,
            seed: int = SEED) -> Projection:
    sc = sc or Scenario()
    t, eg = draws(post, sc, n_draws, seed)
    lo_q, hi_q = param("slow_band_low_q"), param("slow_band_high_q")
    show = t <= param("projection_years") + 1e-9
    q = np.quantile(eg[:, show], [lo_q, 0.5, hi_q], axis=0)
    out = Projection(t[show], q[0], q[1], q[2], scenario=sc.label, group=post.group)
    for name, key in THRESHOLD_KEYS.items():
        thr = param(key)
        yt = years_to_threshold(t, eg, thr)
        # the pessimistic edge of the range is the EARLY crossing (low quantile of the time). "Never within the
        # search" is a sentinel beyond the grid, and quantiles are order statistics, so every edge is a real draw.
        never = t[-1] + 1.0
        yq = np.where(np.isfinite(yt), yt, never)
        lo, med, hi = (float(v) if v < never else float("inf")
                       for v in np.quantile(yq, [lo_q, 0.5, hi_q], method="inverted_cdf"))
        out.years_to[name] = {"threshold": thr, "low": lo, "median": med, "high": hi, "text": _years_text(lo, hi)}
    return out


def compare(post: SlopePosterior, a: Scenario, b: Scenario, at_years: float | None = None,
            seed: int = SEED) -> dict:
    """Range of the eGFR difference (b - a) at ``at_years`` (default: the display horizon), common random numbers."""
    at = param("projection_years") if at_years is None else at_years
    t, ea = draws(post, a, seed=seed)
    _, eb = draws(post, b, seed=seed)
    j = int(np.argmin(np.abs(t - at)))
    d = eb[:, j] - ea[:, j]
    lo_q, hi_q = param("slow_band_low_q"), param("slow_band_high_q")
    return {"at_years": float(t[j]), "low": float(np.quantile(d, lo_q)), "median": float(np.median(d)),
            "high": float(np.quantile(d, hi_q)), "from": a.label, "to": b.label}


def wording(dm: bool, has_aki_scenario: bool) -> list[str]:
    """i18n keys that must accompany an AKI-penalty projection (Amendment 2 A2.7)."""
    keys = ["slow.ranges_only"]
    if has_aki_scenario:
        keys.append("slow.aki_associated")
        if not dm:
            keys.append("slow.aki_extrapolated")
    return keys
