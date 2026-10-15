"""Monte-Carlo 72-hour AKI risk from the twin's posterior (master plan §10.2; Decisions v1 item 5).

Draw states from N(x, P), run the physiology engine 72 h forward (from 08:00 today) with the forecast exposures and
the planned medicines, read creatinine at 08:00 on days +1, +2, +3, and apply exactly the same rule as the training
label: ``kdigo_daily_matrix`` on [last 7 daily estimates, today, 3 future values] with the §9.3 baseline, then
``aki_onsets`` in the future columns. Risk = share of draws with an onset.
"""
from __future__ import annotations

import numpy as np

from vrikka.config import SEED, param
from vrikka.physiology.equations import aki_onsets, kdigo_daily_matrix
from vrikka.physiology.renal import INPUT_DEFAULTS
from vrikka.twin.ukf_twin import KidneyTwin

HORIZON_H = 72
SAMPLE_IDX = (23, 47, 71)        # state after these hours (inputs start at 08:00) = 08:00 on days +1, +2, +3


def aki_risk_72h(twin: KidneyTwin, future: dict, baseline_cr: float, n_draws: int | None = None, seed: int = SEED,
                 overrides: dict | None = None, eff_override: dict | None = None, return_draws: bool = False):
    """P(KDIGO onset within 72 h). ``future`` maps INPUT_DEFAULTS names to 72-hour arrays or scalars.

    ``overrides`` replaces engine parameters for all draws (what-if); ``eff_override`` replaces the current drug
    effect levels (e.g. a drug already paused). The same ``seed`` gives common random numbers across scenarios.
    """
    n = int(n_draws or param("mc_draws_ui"))
    rng = np.random.default_rng(seed)
    P = 0.5 * (twin.P + twin.P.T) + 1e-9 * np.eye(5)
    draws = rng.multivariate_normal(twin.x, P, size=n)
    inputs = {k: np.broadcast_to(np.asarray(future.get(k, v), dtype=float), (HORIZON_H,))
              for k, v in INPUT_DEFAULTS.items()}
    saved = twin.eff
    if eff_override:
        twin.eff = {**twin.eff, **eff_override}
    try:
        cr = twin._run(draws, inputs, overrides, record=("cr",))["cr"]
    finally:
        twin.eff = saved
    future_cr = cr[list(SAMPLE_IDX)].T                              # (n, 3)
    hist = np.array(twin.cr_daily[-8:-1], dtype=float)              # previous up to 7 daily estimates
    today = np.maximum(draws[:, 2], 0.2)[:, None]
    series = np.hstack([np.broadcast_to(hist, (n, hist.size)), today, future_cr])
    stages = kdigo_daily_matrix(series, baseline_cr)
    hit = aki_onsets(stages)[:, -3:].any(axis=1)
    prob = float(hit.mean())
    return (prob, series) if return_draws else prob
