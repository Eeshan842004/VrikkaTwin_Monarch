"""Consolidated summary reports for the presentation (nothing new is computed except the global reason importance):

    python scripts/make_summary_reports.py

- reports/metrics.json         every model x test set x regime: AUROC / AUPRC (95 % CI), Brier, calibration slope and
                               intercept (point estimates; no CI was computed for these), alert-level numbers; copied
                               from reports/fastclock_eval_{mismatched,matched}.json
- reports/reality_checks.json  every reality check with its category (Amendment 2 A2.2), real source, our result and
                               verdict; copied from the individual check reports
- reports/feature_importance.json  model M's global reason importance: mean |LightGBM pred_contrib| per core feature on
                               the held-out 2025 / 2026 mismatched features (frozen model; needs data/features)
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from vrikka.config import DATA_DIR, REPORTS_DIR
from vrikka.fastclock import frozen

SETS = ("internal_test_2024", "test_2025", "test_2026")
ALERT_KEYS = ("red_per_100_patient_days", "amber_plus_red_per_100_patient_days", "sensitivity_red",
              "sensitivity_red_ci95", "sensitivity_amber_or_red", "alerts_per_aki_caught_red",
              "alerts_per_aki_caught_red_ci95", "red_days_per_100_patient_days", "ppv_red_day", "ppv_ceiling_red_day",
              "ppv_red_day_at_1_10_prevalence", "ppv_red_day_at_1_50_prevalence", "ppv_red_alert")


def R(name: str) -> dict:
    p = REPORTS_DIR / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def metrics() -> dict:
    out = {"source": "reports/fastclock_eval_mismatched.json and reports/fastclock_eval_matched.json",
           "note": "Brier and calibration slope / intercept are point estimates (no bootstrap CI was computed)"}
    for regime in ("mismatched", "matched"):
        ev = R(f"fastclock_eval_{regime}")
        out[regime] = {"thresholds": ev["thresholds"], "events_per_feature": ev["events_per_feature"]}
        for s in SETS:
            rows = {}
            for m, v in ev[s].items():
                if m.startswith("_") or m == "subgroup_age_75_plus_M":
                    continue
                d, a = v["day_level"], v["alerts"]
                rows[m] = {"auroc": d["auroc"], "auroc_ci95": d["auroc_ci95"], "auprc": d["auprc"],
                           "auprc_ci95": d["auprc_ci95"], "brier": d["brier"],
                           "calibration_slope": d["calibration_slope"],
                           "calibration_intercept": d["calibration_intercept"],
                           "within_patient_auroc": d["within_patient_auroc"], "prevalence": d["prevalence"],
                           "alerts": {k: a.get(k) for k in ALERT_KEYS}, "lead_time": a["lead_time"]}
            out[regime][s] = rows
    return out


def reality_checks() -> dict:
    r1, r2, r3, r4 = R("r1_validation"), R("r2_overlay"), R("r3_tawam"), R("r4_pmdata")
    l1, cal, l45, noise = R("l1_pooled"), R("calibration_checks"), R("literature_checks_l4_l5"), R("pmdata_noise")
    b = r1["R1b"]["pooled"]
    l4 = l45["L4"]
    l5 = l45["L5"]
    return {"categories": "Amendment 2 A2.2: CALIBRATION may inform parameters; HELD-OUT never used for tuning; "
                          "REVISION-INFORMED motivated the engine revision and is shown next to its v1 failure",
            "checks": [
        {"id": "L1", "category": "CALIBRATION", "source": "Lapi et al., BMJ 2013 (triple therapy RR 1.31; 1.82 in the "
         "first 30 days)", "result": l1["pooled"], "band": l1["pass_band"], "verdict": "PASS" if l1["pooled"]["pass"]
         else "FAIL", "file": "reports/l1_pooled.json"},
        {"id": "L2", "category": "CALIBRATION", "source": cal["L2"]["reference"], "result": cal["L2"],
         "verdict": "DIRECTION CORRECT (loose sanity check)", "file": "reports/calibration_checks.json"},
        {"id": "L4", "category": "REVISION-INFORMED", "source": l4["reference"], "band_pct": l4["target_band_pct"],
         "v1": l4["v1_engine_before_revision"], "v2_twin_engine": l4["twin_engine"],
         "v2_truth_simulator": l4["truth_simulator"], "verdict": "FAIL (stated limitation)",
         "file": "reports/literature_checks_l4_l5.json"},
        {"id": "L5", "category": "REVISION-INFORMED", "source": l5["reference"],
         "v1": l5["v1_engine_gfr_fall_pct"], "v2_dehydration_only": l5["twin_engine_dehydration_only"],
         "v2_with_sustained_exertion": l5["twin_engine_with_sustained_exertion"],
         "verdict": "v1 below range; v2 with exertion inside the reference range (revision-informed, not validation)",
         "file": "reports/literature_checks_l4_l5.json"},
        {"id": "R1a", "category": "HELD-OUT", "source": "MIMIC-IV Clinical Database Demo v2.2 + official mimic-code "
         "KDIGO SQL", "result": {k: r1["R1a"][k] for k in ("agreement_pct", "values_compared", "stays",
                                                          "pass_threshold_pct")},
         "verdict": "PASS" if r1["R1a"]["pass"] else "FAIL", "file": "reports/r1_validation.json"},
        {"id": "R1b", "category": "HELD-OUT", "source": "MIMIC-IV demo + eICU-CRD demo", "result": b,
         "verdict": "FAIL (carry-forward wins)" if not b["kinetic_beats_carry_forward"] else "PASS",
         "file": "reports/r1_validation.json"},
        {"id": "R2", "category": "HELD-OUT", "source": "UCI Chronic Kidney Disease (origin not stated on the UCI page)",
         "result": "lab-distribution overlay", "verdict": "NO PASS/FAIL CLAIM (plausibility only)",
         "claim": r2.get("claim"), "file": "reports/r2_overlay.json"},
        {"id": "R3", "category": "HELD-OUT", "source": r3["dataset"],
         "result": {k: r3[k] for k in ("patients", "events_eGFR_below_60", "c_index_slow_clock_years_to_60",
                                       "c_index_slow_clock_ci95", "c_index_baseline_egfr_alone",
                                       "c_index_baseline_egfr_ci95", "paired_difference_ci95")},
         "verdict": "AS GOOD AS BASELINE eGFR ALONE, NOT BETTER", "file": "reports/r3_tawam.json"},
        {"id": "R4", "category": "HELD-OUT (secondary line)", "source": r4["dataset"],
         "result": {k: r4[k] for k in ("people", "patient_days", "red_notifications_per_100_patient_days",
                                       "amber_plus_red_notifications_per_100_patient_days",
                                       "max_calibrated_probability")},
         "verdict": "PASS (target ~0)" if r4["red_notifications_per_100_patient_days"] == 0 else "FAIL",
         "file": "reports/r4_pmdata.json"},
        {"id": "sigma_hr", "category": "CALIBRATION", "source": "PMData raw Fitbit heart rate (CC BY 4.0)",
         "result": {"sigma_hr_bpm": noise["sigma_hr_bpm"], "people_qualifying": noise["people_qualifying"]},
         "verdict": "USED AS PARAMETER", "file": "reports/pmdata_noise.json"},
        {"id": "SGLT2i", "category": "CALIBRATION (input)", "source": "EMPA-KIDNEY, Lancet Diabetes Endocrinol 2024 "
         "(chronic slope difference 1.37, 95 % CI 1.16-1.59)", "result": "used as the slow-clock input "
         "sglt2i_slope_effect", "verdict": "INPUT, never described as reproduced",
         "file": "config/parameters.yaml; docs/NUMBERS_CHECKED.md"},
    ]}


def importance() -> dict:
    out = {"method": "mean |pred_contrib| (LightGBM native TreeSHAP) of the frozen model M per core feature on the "
                     "held-out mismatched features; eligible days; also the share of days each feature is a top-3 "
                     "risk-raising reason",
           "seasons": {}}
    for year in (2025, 2026):
        f = DATA_DIR / "features" / f"{year}_mismatched.parquet"
        if not f.exists():
            continue
        df = pd.read_parquet(f)
        df = df[~df["excluded"].astype(bool)].sample(n=min(200_000, int((~df["excluded"]).sum())), random_state=42)
        feats = frozen.features("M_hybrid_core25")
        contrib = frozen.booster("M_hybrid_core25").predict(df[feats], pred_contrib=True)[:, :-1]
        mean_abs = np.abs(contrib).mean(axis=0)
        top3 = np.argsort(-contrib, axis=1)[:, :3]
        pos = np.take_along_axis(contrib, top3, axis=1) > 0
        share = {feats[j]: float(((top3 == j) & pos).any(axis=1).mean()) for j in range(len(feats))}
        order = np.argsort(-mean_abs)
        out["seasons"][str(year)] = {"rows_sampled": int(len(df)), "ranking": [
            {"feature": feats[j], "mean_abs_contribution": round(float(mean_abs[j]), 5),
             "share_of_days_in_top3_reasons": round(share[feats[j]], 4)} for j in order]}
    return out


def main() -> int:
    (REPORTS_DIR / "metrics.json").write_text(json.dumps(metrics(), indent=1), encoding="utf-8")
    (REPORTS_DIR / "reality_checks.json").write_text(json.dumps(reality_checks(), indent=1), encoding="utf-8")
    imp = importance()
    if imp["seasons"]:
        (REPORTS_DIR / "feature_importance.json").write_text(json.dumps(imp, indent=1), encoding="utf-8")
        for y, v in imp["seasons"].items():
            print(y, [r["feature"] for r in v["ranking"][:6]])
    print("wrote metrics.json, reality_checks.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
