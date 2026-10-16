"""Build the fast-clock feature tables (master plan §12.2; Amendment 2 A2.3, A2.6).

    python scripts/build_features.py                                  # 2024 + 2025 + 2026, mismatched then matched
    python scripts/build_features.py --years 2024 --regimes mismatched --limit 500     # quick check

Writes data/features/<year>_<regime>.parquet (gitignored): one row per patient-day with the features of
vrikka.fastclock.features, the evaluation labels and, for 2024, the patient-level split (train 60 % / early stopping
10 % / isotonic calibration 15 % / internal test 15 %). 2025 and 2026 rows are the separate test pool (split "test").
Reads only public patient columns, observed data, labs, archived weather and the noisy forecast.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time

import numpy as np
import pandas as pd

from vrikka.config import DATA_DIR, SEED, param
from vrikka.fastclock.features import assign_split, build_shard, forecasts
from vrikka.physiology.exposure import load_season, reference_tables

SYN = DATA_DIR / "synthetic"
OUT = DATA_DIR / "features"
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="*", type=int, default=[2024, 2025, 2026])
    ap.add_argument("--regimes", nargs="*", default=["mismatched", "matched"])
    ap.add_argument("--shard", type=int, default=2500)
    ap.add_argument("--n-draws", type=int, default=int(param("mc_draws_training")))
    ap.add_argument("--limit", type=int, default=None, help="first N patients of each pool (quick checks)")
    a = ap.parse_args()
    t0 = time.time()
    pub = pd.read_parquet(SYN / "patients_public.parquet")
    assert not any(c.startswith("true_") for c in pub.columns), "hidden columns must never reach the features"
    tables = reference_tables()
    split = assign_split(pub.loc[pub["pool"] == "train", "patient_id"].to_numpy())
    OUT.mkdir(parents=True, exist_ok=True)
    for regime in a.regimes:
        for year in a.years:
            pool = pub[pub["pool"] == ("train" if year == 2024 else "test")]
            if a.limit:
                pool = pool.iloc[: a.limit]
            weather = load_season(year)
            D = len(next(iter(weather.values()))) // 24
            fc = forecasts(weather, D, seed=SEED + 1000 * year)
            obs = pd.read_parquet(SYN / str(year) / regime / "observed_daily.parquet")
            labs = pd.read_parquet(SYN / str(year) / regime / "labs.parquet")
            truth = pd.read_parquet(SYN / str(year) / regime / "truth_daily.parquet",
                                    columns=["patient_id", "day", "y", "excluded", "onset", "episode_start", "stage"])
            parts = OUT / f"_{year}_{regime}"
            if parts.exists():
                shutil.rmtree(parts)
            parts.mkdir()
            for k, i in enumerate(range(0, len(pool), a.shard)):
                people = pool.iloc[i:i + a.shard]
                rng = np.random.default_rng(SEED + 7919 * k + year + (0 if regime == "mismatched" else 31))
                df = build_shard(people, obs, labs, truth, weather, fc, year, regime, a.n_draws, rng, tables)
                df["split"] = df["patient_id"].map(split).fillna("test") if year == 2024 else "test"
                df.to_parquet(parts / f"{k:04d}.parquet", index=False)
                print(f"{regime} {year} shard {k}: {len(people)} patients, {len(df)} rows ({time.time() - t0:.0f} s)",
                      flush=True)
                del df
            pd.concat([pd.read_parquet(f) for f in sorted(parts.glob("*.parquet"))], ignore_index=True).to_parquet(
                OUT / f"{year}_{regime}.parquet", index=False)
            shutil.rmtree(parts)
            del obs, labs, truth
    print(f"done in {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
