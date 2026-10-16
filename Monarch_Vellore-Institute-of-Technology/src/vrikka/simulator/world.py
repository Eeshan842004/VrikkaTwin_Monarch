"""One synthetic season end to end: weather -> exposure -> events -> ground truth -> labs -> labels -> devices.

Shared by scripts/generate_cohort.py and scripts/calibration_checks.py so that every number comes from the same code.
Seeds: each patient pool has its own seed; each season's events use ``seed + year`` (Amendment 2 A2.3: the 2025/2026
test seasons use a separate pool of test patients, with new weather and new day-to-day events).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from vrikka.config import SEED
from vrikka.fastclock.labels import baselines_from_labs, episode_starts, make_labels
from vrikka.physiology.exposure import cohort_hourly_sweat
from vrikka.simulator.devices import simulate_observations
from vrikka.simulator.events import simulate_events
from vrikka.simulator.ground_truth import simulate_truth
from vrikka.simulator.labs import simulate_labs
from vrikka.simulator.weather import load_season


@dataclass
class Season:
    year: int
    dates: pd.DatetimeIndex
    weather: dict
    events: dict
    exposure: dict


def build_season(people: pd.DataFrame, year: int, cap_c: float | None = None, sweat_mult: float = 1.0,
                 seed: int = SEED, events: dict | None = None, tables: dict | None = None) -> Season:
    """``events`` lets counterfactual runs (35 degC cap, sweat x0.7 / x1.3) reuse the exact same events;
    ``tables`` reuses the PHS sweat tables across calls."""
    weather = load_season(year)
    days = len(next(iter(weather.values()))) // 24
    ev = events if events is not None else simulate_events(people, days, np.random.default_rng(seed + year))
    ex = cohort_hourly_sweat(weather, people, cap_c=cap_c, sweat_mult=sweat_mult, extra_outdoor_h=ev["extra_outdoor_h"],
                             tables=tables)
    dates = pd.date_range(f"{year}-03-01", periods=days, freq="D")
    return Season(year, dates, weather, ev, ex)


def run_regime(people: pd.DataFrame, season: Season, regime: str, seed: int = SEED,
               with_observations: bool = True) -> dict:
    truth = simulate_truth(people, season.exposure["sweat_l_h"], season.events, regime, seed=seed + season.year,
                           met=season.exposure.get("met"))
    labs = simulate_labs(people, truth["cr_0800"], season.events, np.random.default_rng(seed + season.year + 1))
    base = baselines_from_labs(people, labs)
    lab = make_labels(truth["cr_0800"], base, people["egfr_baseline"].to_numpy())
    lab["episode_start"] = episode_starts(lab["stage"])
    obs = simulate_observations(people, truth, season.events, season.dates,
                                np.random.default_rng(seed + season.year + 2)) if with_observations else None
    return {"truth": truth, "labs": labs, "baseline": base, "labels": lab, "observed": obs}


def long_frame(people: pd.DataFrame, dates: pd.DatetimeIndex, arrays: dict) -> pd.DataFrame:
    """(D, N) arrays -> one row per patient-day."""
    D, N = next(iter(arrays.values())).shape
    out = {"patient_id": np.repeat(people["patient_id"].to_numpy()[None, :], D, 0).ravel(),
           "day": np.repeat(np.arange(D)[:, None], N, 1).ravel(),
           "date": np.repeat(np.asarray(dates)[:, None], N, 1).ravel()}
    for k, v in arrays.items():
        out[k] = np.asarray(v).ravel()
    return pd.DataFrame(out)
