"""Generate the enriched high-risk heat-season cohort (master plan §11; Decisions v1 items 5, 8, 15).

    python scripts/generate_cohort.py                         # N = 3000, 2024 (train) + 2025, 2026 (held-out)
    python scripts/generate_cohort.py --n 1000 --years 2024

Writes (data/synthetic/, gitignored except sample/):
  patients_public.parquet   EHR / profile columns the twin and fast clock may use
  patients_hidden.parquet   true_* parameters (simulator and evaluation only)
  <year>/events_daily.parquet          true events + what the patient/ASHA reported
  <year>/exposure_daily.parquet        daily sweat, outdoor hours, share of hours outside ISO 7933 validity
  <year>/<regime>/truth_daily.parquet  08:00 creatinine/volume, stage, onset, label y, exclusions, episode start
  <year>/<regime>/observed_daily.parquet   wearable / scale / BP observations
  <year>/<regime>/labs.parquet
  sample/                    first 20 patients of 2024 (committed)
and reports/cohort_summary.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import numpy as np

from vrikka.config import DATA_DIR, REPORTS_DIR, SEED
from vrikka.simulator.cohort import generate_cohort, public_columns
from vrikka.simulator.world import build_season, long_frame, run_regime

OUT = DATA_DIR / "synthetic"
EV_KEYS = [
    "fever_excess_c",
    "vomit_episodes",
    "diarrhoea_episodes",
    "poor_intake",
    "nsaid_on",
    "nsaid_units",
    "nsaid_generic",
    "ors_l_day",
    "adherent",
    "sepsis_like",
    "rhabdo",
    "cotrimoxazole",
    "rep_fever_excess_c",
    "rep_vomit_episodes",
    "rep_diarrhoea_episodes",
    "rep_poor_intake",
    "rep_nsaid_on",
    "rep_ors_l_day",
]


def per_day(hourly: np.ndarray, days: int, reducer) -> np.ndarray:
    """(T, N) hourly array -> (days, N) by reducing each 24-hour block."""
    return reducer(hourly.reshape(days, 24, -1), axis=1)


def summarise(people, lab, truth) -> dict:
    ep = lab["episode_start"]
    n, d = len(people), lab["stage"].shape[0]
    ok = ~lab["excluded"]
    return {
        "patients": n,
        "days": d,
        "aki_episodes": int(ep.sum()),
        "raw_onsets": int(lab["onset"].sum()),
        "episodes_per_100_patient_seasons": round(100 * ep.sum() / n, 1),
        "patients_with_any_aki_pct": round(100 * (ep.sum(0) > 0).mean(), 1),
        "aki_patient_days_pct": round(100 * (lab["stage"] > 0).mean(), 2),
        "label_positive_pct_of_eligible_days": round(100 * lab["y"][ok].mean(), 2),
        "onset_stage_counts": {str(s): int(((lab["stage"] == s) & lab["onset"]).sum()) for s in (1, 2, 3)},
        "median_cr_0800": round(float(np.median(truth["cr_0800"])), 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=None)
    ap.add_argument("--years", nargs="*", type=int, default=[2024, 2025, 2026])
    ap.add_argument("--regimes", nargs="*", default=["mismatched", "matched"])
    a = ap.parse_args()
    t0 = time.time()
    people = generate_cohort(a.n, SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    pub = public_columns(people)
    people[pub].to_parquet(OUT / "patients_public.parquet", index=False)
    people[["patient_id"] + [c for c in people.columns if c.startswith("true_")]].to_parquet(
        OUT / "patients_hidden.parquet", index=False
    )
    summary = {"n_patients": len(people), "seed": SEED, "seasons": {}}
    sample_ids = people["patient_id"].iloc[:20]
    for year in a.years:
        season = build_season(people, year)
        ydir = OUT / str(year)
        ydir.mkdir(exist_ok=True)
        ev = long_frame(people, season.dates, {k: season.events[k] for k in EV_KEYS})
        ev.to_parquet(ydir / "events_daily.parquet", index=False)
        ex = season.exposure
        D = len(season.dates)
        expo = long_frame(
            people,
            season.dates,
            {
                "sweat_l": per_day(ex["sweat_l_h"], D, np.sum).round(3),
                "outdoor_h": per_day(ex["outdoors"].astype(float), D, np.sum),
                "outside_iso_share": per_day((~ex["valid"]).astype(float), D, np.mean).round(3),
            },
        )
        expo.to_parquet(ydir / "exposure_daily.parquet", index=False)
        summary["seasons"][str(year)] = {}
        for regime in a.regimes:
            res = run_regime(people, season, regime)
            rdir = ydir / regime
            rdir.mkdir(exist_ok=True)
            lab, tr = res["labels"], res["truth"]
            truth_df = long_frame(
                people,
                season.dates,
                {
                    "cr_0800": tr["cr_0800"].round(4),
                    "v_tot_0800": tr["v_tot_0800"].round(3),
                    "v_ecf_0800": tr["v_ecf_0800"].round(3),
                    "gfr_frac_0800": tr["gfr_frac_0800"].round(4),
                    "cr_max": tr["cr_max"].round(4),
                    "gfr_frac_min": tr["gfr_frac_min"].round(4),
                    "stage": lab["stage"],
                    "onset": lab["onset"],
                    "y": lab["y"],
                    "excluded": lab["excluded"],
                    "episode_start": lab["episode_start"],
                },
            )
            truth_df["baseline_cr"] = np.tile(res["baseline"].round(4), D)
            truth_df.to_parquet(rdir / "truth_daily.parquet", index=False)
            res["observed"].to_parquet(rdir / "observed_daily.parquet", index=False)
            res["labs"].to_parquet(rdir / "labs.parquet", index=False)
            summary["seasons"][str(year)][regime] = summarise(people, lab, tr)
            print(f"{year} {regime}: {summary['seasons'][str(year)][regime]}  ({time.time() - t0:.0f} s)", flush=True)
            if year == 2024 and regime == "mismatched":
                sdir = OUT / "sample"
                sdir.mkdir(exist_ok=True)
                people[pub][people["patient_id"].isin(sample_ids)].to_parquet(
                    sdir / "patients_public.parquet", index=False
                )
                for name, df in (
                    ("truth_daily", truth_df),
                    ("observed_daily", res["observed"]),
                    ("labs", res["labs"]),
                    ("events_daily", ev),
                ):
                    df[df["patient_id"].isin(sample_ids)].to_parquet(sdir / f"{name}.parquet", index=False)
    (REPORTS_DIR / "cohort_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"done in {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
