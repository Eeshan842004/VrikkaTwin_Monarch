"""Generate the enriched high-risk heat-season cohort (master plan §11; Decisions v1 items 5, 8, 15; Amendment 2 A2.3).

    python scripts/generate_cohort.py                  # train pool N = 10,000 (2024) + test pool N = 5,000 (2025, 2026)
    python scripts/generate_cohort.py --n-train 1000 --n-test 500 --years 2024 2025
    python scripts/generate_cohort.py --n-train 3000 --n-test 0 --out data/synthetic/_v1_patients \\
        --summary reports/engine_effect_same_patients.json --no-sample
        # v1 design: ONE pool of 3,000 patients used in all three seasons (isolates the effect of the engine revision)

The 2024 training season uses the train pool (ids P00000...). The 2025 and 2026 test seasons use a separate test pool
(ids T00000..., own seed) so no test patient ever appears in training (Amendment 2 A2.3); with --n-test 0 the train
pool is reused (the v1 design). Patients are processed in shards of --shard patients (memory: about 1 GB of RAM is free
on the development machine); every shard gets its own random stream and is written as a parquet part, then merged.

Writes (data/synthetic/, gitignored except sample/):
  patients_public.parquet   EHR / profile columns the twin and fast clock may use (+ ``pool``: train / test)
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
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from vrikka.config import DATA_DIR, REPORTS_DIR, SEED, load_yaml
from vrikka.physiology.exposure import reference_tables
from vrikka.simulator.cohort import generate_cohort, public_columns
from vrikka.simulator.world import build_season, long_frame, run_regime

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
SHARD_SEED_STEP = 7919


def per_day(hourly: np.ndarray, days: int, reducer) -> np.ndarray:
    """(T, N) hourly array -> (days, N) by reducing each 24-hour block."""
    return reducer(hourly.reshape(days, 24, -1), axis=1)


def summarise(n_patients: int, lab, truth) -> dict:
    ep = lab["episode_start"]
    d = lab["stage"].shape[0]
    ok = ~lab["excluded"]
    return {
        "patients": n_patients,
        "days": d,
        "aki_episodes": int(ep.sum()),
        "raw_onsets": int(lab["onset"].sum()),
        "episodes_per_100_patient_seasons": round(100 * ep.sum() / n_patients, 1),
        "patients_with_any_aki_pct": round(100 * (ep.sum(0) > 0).mean(), 1),
        "aki_patient_days_pct": round(100 * (lab["stage"] > 0).mean(), 2),
        "label_positive_pct_of_eligible_days": round(100 * lab["y"][ok].mean(), 2),
        "label_positive_days": int(lab["y"][ok].sum()),
        "eligible_patient_days": int(ok.sum()),
        "onset_stage_counts": {str(s): int(((lab["stage"] == s) & lab["onset"]).sum()) for s in (1, 2, 3)},
        "median_cr_0800": round(float(np.median(truth["cr_0800"])), 3),
    }


def merge_summaries(parts: list[dict]) -> dict:
    """Combine per-shard season summaries (additive counts; rates recomputed; medians patient-weighted)."""
    n = sum(p["patients"] for p in parts)
    days = parts[0]["days"]
    ep = sum(p["aki_episodes"] for p in parts)
    elig = sum(p["eligible_patient_days"] for p in parts)
    pos = sum(p["label_positive_days"] for p in parts)
    out = {
        "patients": n,
        "days": days,
        "aki_episodes": ep,
        "raw_onsets": sum(p["raw_onsets"] for p in parts),
        "episodes_per_100_patient_seasons": round(100 * ep / n, 1),
        "patients_with_any_aki_pct": round(sum(p["patients_with_any_aki_pct"] * p["patients"] for p in parts) / n, 1),
        "aki_patient_days_pct": round(sum(p["aki_patient_days_pct"] * p["patients"] for p in parts) / n, 2),
        "label_positive_pct_of_eligible_days": round(100 * pos / max(elig, 1), 2),
        "label_positive_days": pos,
        "eligible_patient_days": elig,
        "onset_stage_counts": {s: sum(p["onset_stage_counts"][s] for p in parts) for s in ("1", "2", "3")},
        "median_cr_0800": round(
            float(np.average([p["median_cr_0800"] for p in parts], weights=[p["patients"] for p in parts])), 3
        ),
    }
    return out


class Parts:
    """Shard outputs as parquet parts, merged into one file per table at the end (constant memory)."""

    def __init__(self, root: Path):
        self.root = root / "_parts"
        if self.root.exists():
            shutil.rmtree(self.root)

    def add(self, name: str, df: pd.DataFrame, shard: int) -> None:
        for col in df.columns[df.dtypes.map(lambda t: t == "object")]:
            df[col] = df[col].astype("string")
        path = self.root / name / f"{shard:04d}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)

    def merge(self, dest_root: Path) -> None:
        for d in sorted(p for p in self.root.rglob("*") if p.is_dir() and any(p.glob("*.parquet"))):
            files = sorted(d.glob("*.parquet"))
            dest = dest_root / (str(d.relative_to(self.root)) + ".parquet")
            dest.parent.mkdir(parents=True, exist_ok=True)
            writer = None
            for f in files:
                t = pq.read_table(f)
                if writer is None:
                    writer = pq.ParquetWriter(dest, t.schema)
                writer.write_table(t.cast(writer.schema))
            writer.close()
        shutil.rmtree(self.root)


def main() -> int:
    c = load_yaml("cohort")
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-train", type=int, default=c["n_train_patients"])
    ap.add_argument("--n-test", type=int, default=c["n_test_patients"], help="0 = reuse the train pool (v1 design)")
    ap.add_argument("--years", nargs="*", type=int, default=[2024, 2025, 2026])
    ap.add_argument("--regimes", nargs="*", default=["mismatched", "matched"])
    ap.add_argument("--shard", type=int, default=2500)
    ap.add_argument("--out", type=Path, default=DATA_DIR / "synthetic")
    ap.add_argument("--summary", type=Path, default=REPORTS_DIR / "cohort_summary.json")
    ap.add_argument("--no-sample", action="store_true")
    a = ap.parse_args()
    t0 = time.time()

    train = generate_cohort(a.n_train, SEED, "P")
    train["pool"] = "train"
    if a.n_test:
        test = generate_cohort(a.n_test, SEED + c["test_pool_seed_offset"], "T")
        test["pool"] = "test"
        allp = pd.concat([train, test], ignore_index=True)
    else:
        test, allp = train, train
    a.out.mkdir(parents=True, exist_ok=True)
    pub = public_columns(allp)
    allp[pub].to_parquet(a.out / "patients_public.parquet", index=False)
    allp[["patient_id"] + [col for col in allp.columns if col.startswith("true_")]].to_parquet(
        a.out / "patients_hidden.parquet", index=False
    )
    summary = {
        "n_train_patients": len(train),
        "n_test_patients": len(test) if a.n_test else 0,
        "test_pool": "separate patients (own seed)" if a.n_test else "reuses the train pool (v1 design)",
        "seed": SEED,
        "shard": a.shard,
        "seasons": {},
    }
    tables = reference_tables()
    sample_ids = set(train["patient_id"].iloc[:20])
    for year in a.years:
        pool = train if year == 2024 else test
        pub_cols = public_columns(pool)
        parts = Parts(a.out / str(year))
        shard_sums: dict[str, list[dict]] = {r: [] for r in a.regimes}
        for k, i in enumerate(range(0, len(pool), a.shard)):
            people = pool.iloc[i : i + a.shard].reset_index(drop=True)
            seed = SEED + SHARD_SEED_STEP * k + (c["test_pool_seed_offset"] if year != 2024 and a.n_test else 0)
            season = build_season(people, year, seed=seed, tables=tables)
            ev = long_frame(people, season.dates, {key: season.events[key] for key in EV_KEYS})
            parts.add("events_daily", ev, k)
            ex = season.exposure
            D = len(season.dates)
            parts.add(
                "exposure_daily",
                long_frame(
                    people,
                    season.dates,
                    {
                        "sweat_l": per_day(ex["sweat_l_h"], D, np.sum).round(3),
                        "outdoor_h": per_day(ex["outdoors"].astype(np.float32), D, np.sum),
                        "outside_iso_share": per_day((~ex["valid"]).astype(np.float32), D, np.mean).round(3),
                        "mean_met": per_day(ex["met"], D, np.mean).round(2),
                    },
                ),
                k,
            )
            for regime in a.regimes:
                res = run_regime(people, season, regime, seed=seed)
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
                parts.add(f"{regime}/truth_daily", truth_df, k)
                parts.add(f"{regime}/observed_daily", res["observed"], k)
                parts.add(f"{regime}/labs", res["labs"], k)
                shard_sums[regime].append(summarise(len(people), lab, tr))
                if year == 2024 and regime == "mismatched" and k == 0 and not a.no_sample:
                    sdir = a.out / "sample"
                    sdir.mkdir(exist_ok=True)
                    people[pub_cols][people["patient_id"].isin(sample_ids)].to_parquet(
                        sdir / "patients_public.parquet", index=False
                    )
                    for name, df in (
                        ("truth_daily", truth_df),
                        ("observed_daily", res["observed"]),
                        ("labs", res["labs"]),
                        ("events_daily", ev),
                    ):
                        df[df["patient_id"].isin(sample_ids)].to_parquet(sdir / f"{name}.parquet", index=False)
                del res, truth_df, lab, tr
            print(f"{year} shard {k} ({len(people)} patients) done  ({time.time() - t0:.0f} s)", flush=True)
            del season, ev, ex
        parts.merge(a.out / str(year))
        summary["seasons"][str(year)] = {r: merge_summaries(v) for r, v in shard_sums.items()}
        for regime, s in summary["seasons"][str(year)].items():
            print(f"{year} {regime}: {s}", flush=True)
    a.summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"done in {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
