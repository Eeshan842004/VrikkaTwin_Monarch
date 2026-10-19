"""Feature tables for the robustness analyses of EVAL_PLAN §15.4 and Amendment 1 A1.8 (Part 7).

    python scripts/build_robustness_features.py                       # every variant, 2025 test season, mismatched
    python scripts/build_robustness_features.py --variants no_band --limit 500

Same patients (the 2025 held-out test pool), same truth, same labels; only what the twin SEES changes. The frozen
Part 4 model scores the result (scripts/evaluate.py): nothing is refitted or re-thresholded.
Variants:
  no_band           band signals removed (resting HR, steps, sleep, skin temperature); scale and BP kept
  tier0_only        everyone observed like Tier 0: no band, weight and BP only on the weekly ASHA visit day
  drop30, drop50    30 % / 50 % of band days removed at random
  noise2x           weight, resting-HR and SBP noise doubled (extra noise with sqrt(3) x the registry SD)
  perfect_forecast  the archived weather as the 72-h forecast (the headline always uses the noisy forecast)
Writes data/features/robust_<variant>_<year>_<regime>.parquet (gitignored).
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time

import numpy as np
import pandas as pd

from vrikka.config import DATA_DIR, SEED, load_yaml, param
from vrikka.fastclock.features import build_shard, forecasts
from vrikka.physiology.exposure import load_season, reference_tables

SYN = DATA_DIR / "synthetic"
OUT = DATA_DIR / "features"
BAND = ["resting_hr", "steps", "sleep_hours", "skin_temp_delta"]
VARIANTS = ("no_band", "tier0_only", "drop30", "drop50", "noise2x", "perfect_forecast")


def modify(obs: pd.DataFrame, variant: str, rng: np.random.Generator) -> pd.DataFrame:
    o = obs.copy()
    if variant == "no_band":
        o[BAND] = np.nan
    elif variant == "tier0_only":
        visit = pd.to_datetime(o["date"]).dt.dayofweek == load_yaml("cohort")["asha_visit_weekday"]
        o[BAND] = np.nan
        o.loc[~visit, ["weight_morning", "sbp_home"]] = np.nan
    elif variant in ("drop30", "drop50"):
        share = 0.3 if variant == "drop30" else 0.5
        drop = rng.random(len(o)) < share
        o.loc[drop, BAND] = np.nan
    elif variant == "noise2x":
        k = np.sqrt(3.0)                         # extra SD so that total noise variance is 4x (SD x2)
        for col, sd in (("weight_morning", param("sigma_weight_kg")), ("resting_hr", param("sigma_hr_bpm")),
                        ("sbp_home", param("sigma_sbp_mmhg"))):
            m = o[col].notna()
            o.loc[m, col] = o.loc[m, col] + rng.normal(0.0, k * sd, int(m.sum()))
    return o


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", nargs="*", default=list(VARIANTS), choices=VARIANTS)
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--regime", default="mismatched")
    ap.add_argument("--shard", type=int, default=2500)
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    t0 = time.time()
    pub = pd.read_parquet(SYN / "patients_public.parquet")
    pool = pub[pub["pool"] == "test"]
    if a.limit:
        pool = pool.iloc[: a.limit]
    tables = reference_tables()
    weather = load_season(a.year)
    D = len(next(iter(weather.values()))) // 24
    obs0 = pd.read_parquet(SYN / str(a.year) / a.regime / "observed_daily.parquet")
    labs = pd.read_parquet(SYN / str(a.year) / a.regime / "labs.parquet")
    truth = pd.read_parquet(SYN / str(a.year) / a.regime / "truth_daily.parquet",
                            columns=["patient_id", "day", "y", "excluded", "onset", "episode_start", "stage"])
    for variant in a.variants:
        fc = forecasts(weather, D, seed=SEED + 1000 * a.year, perfect=variant == "perfect_forecast")
        obs = obs0 if variant == "perfect_forecast" else modify(obs0, variant, np.random.default_rng(SEED + 77))
        parts = OUT / f"_robust_{variant}"
        if parts.exists():
            shutil.rmtree(parts)
        parts.mkdir(parents=True)
        for k, i in enumerate(range(0, len(pool), a.shard)):
            people = pool.iloc[i:i + a.shard]
            # the same random streams as the headline build, so differences come from the variant alone
            rng = np.random.default_rng(SEED + 7919 * k + a.year + (0 if a.regime == "mismatched" else 31))
            df = build_shard(people, obs, labs, truth, weather, fc, a.year, a.regime,
                             int(param("mc_draws_training")), rng, tables)
            df["split"], df["variant"] = "test", variant
            df.to_parquet(parts / f"{k:04d}.parquet", index=False)
            print(f"{variant} shard {k}: {len(people)} patients ({time.time() - t0:.0f} s)", flush=True)
        pd.concat([pd.read_parquet(f) for f in sorted(parts.glob("*.parquet"))], ignore_index=True).to_parquet(
            OUT / f"robust_{variant}_{a.year}_{a.regime}.parquet", index=False)
        shutil.rmtree(parts)
    print(f"done in {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
