"""R3: slow-clock risk ranking on the Tawam CKD cohort (EVAL_PLAN §15.1; Amendment 1 A1.7; Amendment 2 A2.2).

    python scripts/validate_r3.py          # needs data/raw/tawam/tawam_ckd_S2.xlsx (scripts/download_public_data.py)

Held-out check (never used for tuning). Tawam (Al-Shamsi et al., PLoS ONE 2018; 491 patients, UAE) has baseline
values and the time to CKD stage 3-5 (eGFR < 60), but NO serial eGFR, so this tests the slow clock's RANKING of who
reaches eGFR < 60 sooner, not a personal slope. For each patient the slow clock is fitted with the baseline eGFR as its
only observation and the registry prior for the patient's group (diabetes or not; no UACR in the data, so the
albuminuria prior is never used), and the median years to eGFR < 60 is the score. Reported next to "baseline eGFR
alone" (the obvious comparator) with patient-level bootstrap CIs. KFRE needs eGFR 10-59 and a UACR: neither holds
here, so it is reported as not applicable. Nothing in the registry is changed by this check.
Writes reports/r3_tawam.json.
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd
from lifelines.utils import concordance_index

from vrikka.config import DATA_DIR, REPORTS_DIR, SEED, param
from vrikka.physiology.equations import kfre_is_valid
from vrikka.slowclock.bayes_slope import fit
from vrikka.slowclock.projection import project

N_BOOT = 1000
SRC = DATA_DIR / "raw" / "tawam" / "tawam_ckd_S2.xlsx"


def years_to_60(egfr: float, dm: bool) -> float:
    post = fit([(0.0, float(egfr))], egfr_now=float(egfr), dm=bool(dm))
    yt = project(post, n_draws=int(param("slow_mc_draws")), seed=SEED).years_to["g3a"]["median"]
    return yt if np.isfinite(yt) else param("projection_search_years") + 1.0      # "> 15 years" ties at the top


def boot_ci(vals: list[float]) -> list[float]:
    return [round(float(x), 4) for x in np.percentile(vals, [2.5, 97.5])]


def main() -> int:
    if not SRC.exists():
        print(f"missing {SRC}; run scripts/download_public_data.py --only tawam")
        return 1
    df = pd.read_excel(SRC, sheet_name=0)
    t = df["TimeToEventMonths"].to_numpy(float) / 12.0
    ev = df["EventCKD35"].to_numpy(int)
    egfr = df["eGFRBaseline"].to_numpy(float)
    dm = df["HistoryDiabetes"].to_numpy(bool)
    cache: dict = {}
    score = np.array([cache.setdefault((round(e, 3), d), years_to_60(e, d)) for e, d in zip(egfr, dm, strict=True)])
    c_slow = concordance_index(t, score, ev)
    c_egfr = concordance_index(t, egfr, ev)
    rng = np.random.default_rng(SEED)
    bs_slow, bs_egfr, bs_diff = [], [], []
    n = len(df)
    for _ in range(N_BOOT):
        i = rng.integers(0, n, n)
        if ev[i].sum() == 0:
            continue
        a, b = concordance_index(t[i], score[i], ev[i]), concordance_index(t[i], egfr[i], ev[i])
        bs_slow.append(a)
        bs_egfr.append(b)
        bs_diff.append(a - b)
    sub = {}
    for name, mask in (("diabetes", dm), ("no_diabetes", ~dm)):
        if ev[mask].sum() > 0:
            sub[name] = {"patients": int(mask.sum()), "events": int(ev[mask].sum()),
                         "c_index_slow_clock": round(concordance_index(t[mask], score[mask], ev[mask]), 4),
                         "c_index_baseline_egfr": round(concordance_index(t[mask], egfr[mask], ev[mask]), 4)}
    out = {
        "check": "R3 (held-out; Amendment 2 A2.2)",
        "dataset": "Tawam CKD cohort, Al-Shamsi et al., PLoS ONE 13(6): e0199920 (2018), S2 data (CC BY 4.0)",
        "question": "does the slow clock rank who reaches eGFR < 60 sooner? (ranking, not a personal-slope test)",
        "patients": int(n), "events_eGFR_below_60": int(ev.sum()),
        "followup_years_median": round(float(np.median(t)), 2),
        "baseline_egfr_range": [round(float(egfr.min()), 1), round(float(egfr.max()), 1)],
        "c_index_slow_clock_years_to_60": round(float(c_slow), 4), "c_index_slow_clock_ci95": boot_ci(bs_slow),
        "c_index_baseline_egfr_alone": round(float(c_egfr), 4), "c_index_baseline_egfr_ci95": boot_ci(bs_egfr),
        "paired_difference_slow_minus_egfr": round(float(c_slow - c_egfr), 4),
        "paired_difference_ci95": boot_ci(bs_diff),
        "by_diabetes": sub,
        "kfre": {"valid_patients": int(sum(kfre_is_valid(e, None) for e in egfr)),
                 "note": "not applicable: every baseline eGFR is >= 60 and the data have no UACR (KFRE needs eGFR "
                         "10-59 with a UACR)"},
        "method": "score = median years to eGFR < 60 from the slow clock (baseline eGFR as the only observation, "
                  "registry slope prior by diabetes status, AKI penalty not applied); '> 15 years' tie at the top. "
                  "Harrell's C (lifelines) against TimeToEventMonths / EventCKD35; patient-level bootstrap "
                  f"({N_BOOT}) percentile CIs. No parameter was changed for or after this check.",
        "bootstrap_resamples": len(bs_slow),
    }
    (REPORTS_DIR / "r3_tawam.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("patients", "events_eGFR_below_60", "c_index_slow_clock_years_to_60",
                                          "c_index_slow_clock_ci95", "c_index_baseline_egfr_alone",
                                          "c_index_baseline_egfr_ci95", "paired_difference_ci95")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
