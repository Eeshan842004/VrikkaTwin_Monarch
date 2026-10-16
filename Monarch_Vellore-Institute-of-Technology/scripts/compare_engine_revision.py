"""Old vs new after the 16 Oct engine revision (Decisions v4 §7 step 4; Amendment 2 A2.4). Reads only report JSONs:
reports/v1_engine/* (v1 engine, 3,000 patients), reports/engine_effect_same_patients_* (new engine, the SAME 3,000
patients and seeds: isolates the engine change) and the new headline reports (new engine, 10,000 train / 5,000 test).
Writes reports/engine_revision_comparison.json.
"""
from __future__ import annotations

import json
import sys

from vrikka.config import REPORTS_DIR

V1 = REPORTS_DIR / "v1_engine"


def j(path):
    return json.loads(path.read_text(encoding="utf-8"))


def scenarios(d: dict) -> dict:
    a = d["registry_defaults"]["actual"]
    return {k: {"dcr_0800": v["peak_delta_cr_0800_mg_dl"], "dcr_hourly_peak": v["peak_delta_cr_hourly_mg_dl"],
                "kdigo": v["kdigo_max_stage_0800"]} for k, v in a.items() if not k.startswith("_")}


def season_rows(summary: dict) -> dict:
    return {y: {r: {k: s[k] for k in ("patients", "aki_episodes", "episodes_per_100_patient_seasons",
                                       "label_positive_pct_of_eligible_days")}
                for r, s in regimes.items()} for y, regimes in summary["seasons"].items()}


def haf(c: dict) -> dict:
    return {"overall": c["haf"]["all"].get("haf"), "overall_ci95": c["haf"]["all"].get("haf_ci95"),
            "subgroups": {k: v.get("haf") for k, v in c["haf"].items()},
            "sweat_x0.7": c["sweat_sensitivity"]["x0.7"]["haf"], "sweat_x1.3": c["sweat_sensitivity"]["x1.3"]["haf"],
            "matched": c["haf_matched_regime"]["haf"]}


def main() -> int:
    out = {"note": "v1 = engine before the revision (3,000 patients). same_patients = new engine, identical 3,000 "
                   "patients and seeds (the engine effect alone). new = new engine, 10,000 train / 5,000 separate test "
                   "patients (headline)."}
    out["g2_scenarios_kamala_like_nagpur"] = {"v1": scenarios(j(V1 / "physiology_scenarios.json")),
                                             "new": scenarios(j(REPORTS_DIR / "physiology_scenarios.json"))}
    l45, l45v1 = j(REPORTS_DIR / "literature_checks_l4_l5.json"), j(V1 / "literature_checks_l4_l5.json")
    out["L4_cross_shift"] = {"v1_engine": l45v1["L4"]["default"], "new_twin_engine": l45["L4"]["twin_engine"],
                             "new_truth_simulator": l45["L4"]["truth_simulator"],
                             "band_pct": l45["L4"]["target_band_pct"]}
    out["L5_gfr_fall_pct"] = {k: l45["L5"][k] for k in ("v1_engine_gfr_fall_pct", "twin_engine_dehydration_only",
                                                        "twin_engine_with_sustained_exertion",
                                                        "truth_simulator_dehydration_only",
                                                        "truth_simulator_with_sustained_exertion")}
    out["event_rates"] = {"v1": season_rows(j(V1 / "cohort_summary.json")),
                          "same_patients": season_rows(j(REPORTS_DIR / "engine_effect_same_patients_cohort.json")),
                          "new": season_rows(j(REPORTS_DIR / "cohort_summary.json"))}
    out["heat_attributable_fraction"] = {"v1": haf(j(V1 / "calibration_checks.json"))}
    sp = REPORTS_DIR / "engine_effect_same_patients_calibration.json"
    if sp.exists():
        out["heat_attributable_fraction"]["same_patients"] = haf(j(sp))
    out["heat_attributable_fraction"]["new"] = haf(j(REPORTS_DIR / "calibration_checks.json"))
    out["L1_pooled"] = {"v1": j(V1 / "l1_pooled.json")["pooled"],
                        "same_patients": j(REPORTS_DIR / "engine_effect_same_patients_l1.json")["pooled"],
                        "new": j(REPORTS_DIR / "l1_pooled.json")["pooled"]}
    dv1, dn = j(V1 / "demo_numbers.json")["scenarios"], j(REPORTS_DIR / "demo_numbers.json")["scenarios"]
    out["demo_personas"] = {k: {"v1": {x: dv1[k]["summary"][x] for x in ("max_risk", "first_red_day",
                                                                        "truth_aki_onset_day", "lead_time_h",
                                                                        "max_intra_day_rise_mg_dl")},
                                "new": {x: dn[k]["summary"][x] for x in ("max_risk", "first_red_day",
                                                                        "truth_aki_onset_day", "lead_time_h",
                                                                        "max_intra_day_rise_mg_dl")}}
                            for k in dn if k in dv1}
    out["demo_personas"]["S1_kamala_whatif"] = {"v1": dv1["S1_kamala"].get("whatif_72h_risk"),
                                                "new": dn["S1_kamala"].get("whatif_72h_risk")}
    (REPORTS_DIR / "engine_revision_comparison.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
