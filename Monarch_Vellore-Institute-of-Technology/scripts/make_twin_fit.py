"""'How well does the twin know this patient?' -> reports/twin_fit.json (optional feature a).

    python scripts/make_twin_fit.py

For each fictional persona's demo replay (the same deterministic replay as reports/demo_numbers.json): each morning's
twin-PREDICTED weight and resting HR (before the update) against what was OBSERVED, the prediction error and its
running mean absolute value, and the learned sweat multiplier with its 80 % interval. Personalisation progress = how
much the uncertainty of the sweat multiplier has shrunk from its prior (1 - posterior SD / prior SD of log theta).
The personas have no lab draws in the replay, so creatinine is shown as the twin's estimate next to the demo truth
(no observed lab).
"""
from __future__ import annotations

import inspect
import json
import sys

import numpy as np

from vrikka.config import REPORTS_DIR, load_yaml, param
from vrikka.twin.replay import replay

Z80 = 1.2815515655446004       # two-sided 80 % normal quantile
THETA_TRUE = inspect.signature(replay).parameters["theta_true"].default     # the demo world's true value


def main() -> int:
    sc = load_yaml("scenarios")
    sd0 = param("ukf_p0_log_theta")
    out = {"note": "fictional personas, demo replay on real 2024 weather; predicted = the twin's expectation of the "
                   "morning reading before it saw it; no lab draws in the replay (creatinine: twin estimate vs demo "
                   "truth)", "prior_log_theta_sd": sd0, "personas": {}}
    for pid, cfg in sc.items():
        r = replay(pid, cfg)
        fit = r.fit
        err_w = np.array([f["weight_observed"] - f["weight_predicted"] for f in fit])
        err_hr = np.array([f["hr_observed"] - f["hr_predicted"] for f in fit])
        days = []
        for k, f in enumerate(fit):
            sd = f["log_theta_sd"]
            days.append({
                "date": r.dates[k], "weight_predicted": round(f["weight_predicted"], 2),
                "weight_observed": round(f["weight_observed"], 2), "weight_error": round(float(err_w[k]), 2),
                "weight_mae_so_far": round(float(np.abs(err_w[: k + 1]).mean()), 3),
                "hr_predicted": round(f["hr_predicted"], 1), "hr_observed": round(f["hr_observed"], 1),
                "hr_error": round(float(err_hr[k]), 1),
                "theta": round(f["theta"], 3), "theta_80": [round(float(np.exp(np.log(f["theta"]) - Z80 * sd)), 3),
                                                             round(float(np.exp(np.log(f["theta"]) + Z80 * sd)), 3)],
                "personalisation_pct": round(100 * (1 - sd / sd0), 1),
                "twin_cr": round(r.twin_cr[k], 3), "truth_cr": round(r.truth_cr[k], 3)})
        half = len(err_w) // 2
        out["personas"][pid] = {
            "label": cfg["label"], "theta_true_demo": THETA_TRUE, "days": days,
            "weight_mae_first_half": round(float(np.abs(err_w[:half]).mean()), 3),
            "weight_mae_second_half": round(float(np.abs(err_w[half:]).mean()), 3),
            "sigma_weight_kg": param("sigma_weight_kg"),
            "personalisation_pct_final": days[-1]["personalisation_pct"]}
        print(pid, out["personas"][pid]["weight_mae_first_half"], out["personas"][pid]["weight_mae_second_half"],
              days[-1]["personalisation_pct"], days[-1]["theta"])
    (REPORTS_DIR / "twin_fit.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
