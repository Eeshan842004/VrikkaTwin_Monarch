"""Training labels (master plan §12.1; Decisions v1 item 5).

y = 1 if a KDIGO stage >= 1 STARTS on one of the next three daily 08:00 values (within 72 h of the 09:00 prediction).
Labels are computed on the ground-truth daily 08:00 creatinine with the §9.3 baseline (mean of the two stable
pre-season labs), through exactly the same functions the twin's Monte-Carlo risk uses
(``kdigo_daily_matrix`` + ``aki_onset_within``).
Excluded days: already in AKI, the 7 days after an episode ends, and baseline eGFR < 15.
The label means "true (simulated) AKI by daily creatinine"; in real life AKI is only detected when a test is done.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from vrikka.physiology.equations import aki_onset_within, aki_onsets, baseline_creatinine, kdigo_daily_matrix


def baselines_from_labs(people: pd.DataFrame, labs: pd.DataFrame) -> np.ndarray:
    pre = labs[labs["reason"] == "pre_season"]
    out = []
    for r in people.itertuples(index=False):
        rows = pre[pre["patient_id"] == r.patient_id]
        out.append(baseline_creatinine(list(zip(rows["day"], rows["creatinine_mg_dl"], strict=True)), 0,
                                       r.age, r.female)[0])
    return np.array(out)


def make_labels(cr_0800: np.ndarray, baseline: np.ndarray, egfr_baseline: np.ndarray,
                horizon_days: int = 3) -> dict[str, np.ndarray]:
    """``cr_0800`` (D, N) -> dict of (D, N) arrays: stage, onset, y, excluded."""
    stages = kdigo_daily_matrix(cr_0800.T, baseline).T
    onset = aki_onsets(stages.T).T
    y = aki_onset_within(stages.T, horizon_days).T
    in_aki = stages > 0
    after = np.zeros_like(in_aki)
    D = stages.shape[0]
    ended = in_aki[:-1] & ~in_aki[1:]                         # episode ended on day d+1
    for d, i in zip(*np.nonzero(ended), strict=True):
        after[d + 1:min(d + 8, D), i] = True
    excluded = in_aki | after | (np.asarray(egfr_baseline) < 15)[None, :]
    return {"stage": stages, "onset": onset, "y": y & ~excluded, "excluded": excluded}


def episode_starts(stage: np.ndarray, gap_days: int = 7) -> np.ndarray:
    """Distinct AKI episodes for counting (event rates, heat-attributable fraction): an onset counts as a new episode
    only if at least ``gap_days`` stage-0 days separate it from the previous episode (the same 7-day window the
    labels exclude after an episode). ``stage`` is (D, N)."""
    s = np.asarray(stage) > 0
    D, N = s.shape
    starts = np.zeros_like(s)
    for i in range(N):
        last_aki = -10 ** 6
        for d in range(D):
            if s[d, i]:
                if d - last_aki > gap_days:
                    starts[d, i] = True
                last_aki = d
    return starts
