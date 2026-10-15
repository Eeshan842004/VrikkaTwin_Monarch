"""Lab sampling (master plan §11.1): two stable pre-season labs, sparse routine labs, symptom-triggered labs.

Lab creatinine = true 08:00 creatinine x (1 + N(0, cr_lab_cv)). Labs are sparse (routine every 30-120 days), which is
exactly why the twin estimates creatinine between labs and advises when to test.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from vrikka.config import load_yaml, param


def simulate_labs(people: pd.DataFrame, cr_0800: np.ndarray, ev: dict, rng: np.random.Generator) -> pd.DataFrame:
    c = load_yaml("cohort")
    D, N = cr_0800.shape
    cv = param("cr_lab_cv")
    rows = []
    for i, pid in enumerate(people["patient_id"]):
        base = people["cr_baseline"].iat[i]
        for day in c["pre_season_labs_days"]:               # stable outpatient labs before the season
            rows.append((pid, day, base * (1 + rng.normal(0, cv)), "pre_season"))
        first = int(rng.integers(0, max(int(c["lab_schedule_days"]["routine_mean"]), 1)))
        day = first
        while day < D:
            rows.append((pid, day, cr_0800[day, i] * (1 + rng.normal(0, cv)), "routine"))
            day += int(rng.integers(30, 121))
        sym_start = np.nonzero((ev["fever_excess_c"][:, i] > 0) | (ev["vomit_episodes"][:, i] > 0))[0]
        starts = sym_start[np.r_[True, np.diff(sym_start) > 1]] if sym_start.size else []
        for s in starts:
            if rng.random() < c["lab_schedule_days"]["symptom_triggered_prob"]:
                d = int(min(s + rng.integers(1, 3), D - 1))
                rows.append((pid, d, cr_0800[d, i] * (1 + rng.normal(0, cv)), "symptom_triggered"))
    labs = pd.DataFrame(rows, columns=["patient_id", "day", "creatinine_mg_dl", "reason"])
    labs["creatinine_mg_dl"] = labs["creatinine_mg_dl"].round(3)
    return labs.sort_values(["patient_id", "day"]).reset_index(drop=True)
