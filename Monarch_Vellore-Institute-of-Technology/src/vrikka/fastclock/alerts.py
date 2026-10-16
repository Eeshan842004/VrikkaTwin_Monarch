"""Alert policy: green / amber / red, with hysteresis and 72-hour de-duplication (master plan §12.5; Amendment 2 A2.5).

- RED (doctor review + home kidney test): a raised red notification at most 0.5 per 100 patient-days.
- AMBER (patient self-care: ORS within guardrails, avoid painkillers, shade): amber + red notifications together at most
  3 per 100 patient-days.
- A red state clears only when the risk falls below ``red_clear_ratio`` x the red threshold (config/alert_policy.yaml:
  0.10 / 0.15 of the provisional thresholds) on a later day; a new notification of the same level is not raised within
  ``dedup_hours`` (72 h) of the previous one. Excluded days (already in AKI or recovering) end any alert state.
- Thresholds are tuned on the 2024 calibration split only, then frozen.
States are computed for (N, D) arrays: one row per patient, one column per day at 09:00.
"""
from __future__ import annotations

import numpy as np

from vrikka.config import load_yaml

GREEN, AMBER, RED = 0, 1, 2


def policy() -> dict:
    p = load_yaml("alert_policy")
    lv = p["levels"]
    return {"red_clear_ratio": p["hysteresis"]["red_clear_below"] / lv["amber"]["max_prob"],
            "dedup_days": int(p["dedup_hours"] // 24), "red_budget": p["red_budget_per_100_patient_days"],
            "total_budget": p["alert_budget_per_100_patient_days"]}


def alert_states(prob: np.ndarray, eligible: np.ndarray, red_thr: float, amber_thr: float,
                 clear_ratio: float | None = None, dedup_days: int | None = None) -> dict[str, np.ndarray]:
    """prob, eligible (N, D) -> level (N, D) and raised red / amber notifications (N, D) booleans."""
    pol = policy()
    clear_ratio = pol["red_clear_ratio"] if clear_ratio is None else clear_ratio
    dedup = pol["dedup_days"] if dedup_days is None else dedup_days
    N, D = prob.shape
    level = np.zeros((N, D), dtype=np.int8)
    red_raised = np.zeros((N, D), dtype=bool)
    amber_raised = np.zeros((N, D), dtype=bool)
    in_red = np.zeros(N, dtype=bool)
    last_red = np.full(N, -10 ** 6)
    last_amber = np.full(N, -10 ** 6)
    prev = np.zeros(N, dtype=np.int8)
    for d in range(D):
        p, ok = prob[:, d], eligible[:, d]
        in_red = ok & np.where(in_red, p >= clear_ratio * red_thr, p >= red_thr)
        lv = np.where(in_red, RED, np.where(ok & (p >= amber_thr), AMBER, GREEN)).astype(np.int8)
        new_red = (lv == RED) & (prev != RED) & (d - last_red > dedup)
        new_amber = (lv == AMBER) & (prev == GREEN) & (d - last_amber > dedup)
        last_red = np.where(new_red, d, last_red)
        last_amber = np.where(new_amber, d, last_amber)
        red_raised[:, d], amber_raised[:, d], level[:, d] = new_red, new_amber, lv
        prev = lv
    return {"level": level, "red_raised": red_raised, "amber_raised": amber_raised}


def rates(st: dict, eligible: np.ndarray) -> tuple[float, float]:
    n = max(int(eligible.sum()), 1)
    red = 100.0 * st["red_raised"].sum() / n
    return red, red + 100.0 * st["amber_raised"].sum() / n


def tune_thresholds(prob: np.ndarray, eligible: np.ndarray, red_budget: float | None = None,
                    total_budget: float | None = None) -> dict:
    """Lowest thresholds that keep red <= red_budget and amber + red <= total_budget per 100 patient-days."""
    pol = policy()
    red_budget = pol["red_budget"] if red_budget is None else red_budget
    total_budget = pol["total_budget"] if total_budget is None else total_budget
    vals = np.unique(np.round(prob[eligible], 6))
    vals = vals[vals > 0]
    hi_big = 1.0 + 1e-9

    def search(fn_ok, lo_idx: int) -> float:
        lo, hi = lo_idx, len(vals) - 1                   # smallest index whose threshold satisfies the budget
        if lo > hi or not fn_ok(vals[hi]):
            return hi_big
        while lo < hi:
            mid = (lo + hi) // 2
            if fn_ok(vals[mid]):
                hi = mid
            else:
                lo = mid + 1
        return float(vals[lo])

    red = search(lambda t: rates(alert_states(prob, eligible, t, hi_big), eligible)[0] <= red_budget, 0)
    amber = search(lambda t: rates(alert_states(prob, eligible, red, t), eligible)[1] <= total_budget, 0)
    amber = min(amber, red)
    st = alert_states(prob, eligible, red, amber)
    r, tot = rates(st, eligible)
    return {"red_threshold": red, "amber_threshold": amber, "red_per_100_patient_days_on_calibration": round(r, 3),
            "amber_plus_red_per_100_patient_days_on_calibration": round(tot, 3),
            "red_clear_ratio": pol["red_clear_ratio"], "dedup_days": pol["dedup_days"],
            "budgets": {"red": red_budget, "amber_plus_red": total_budget}}
