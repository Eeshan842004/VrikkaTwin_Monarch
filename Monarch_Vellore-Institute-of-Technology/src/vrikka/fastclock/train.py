"""Fast-clock models: baselines B0-B4 and the hybrid model M (master plan §12.3-§12.4; Amendment 2 A2.6).

- B0 last-lab logistic regression (last lab creatinine / baseline, days since that lab, baseline eGFR).
- B1 heat-index rule: forecast heat index >= 41 degC AND (age >= 60 or on a diuretic) -> 1, else 0.
- B2 transparent points: triple whammy today + forecast heat index >= 41 + baseline eGFR < 60 (0-3).
- B3 plain LightGBM on the raw inputs (no twin, no Monte-Carlo risk).
- B4 the twin's physics risk alone (``mc_risk_72h``).
- M  LightGBM on the <= 25 core features (twin posterior + Monte-Carlo risk + key drugs / symptoms / exposure) with
     monotone constraints, ``min_data_in_leaf`` >= 50 and early stopping on the 2024 early-stopping split; then
     isotonic calibration on the 2024 calibration split. M_full (about 60 features) is a sensitivity row only.
All fitting, early stopping and calibration use 2024 only (Amendment 2 A2.6).
"""
from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from vrikka.fastclock.features import B0, CORE, FULL, RAW

LGB_PARAMS = {
    "objective": "binary", "learning_rate": 0.03, "num_leaves": 15, "min_data_in_leaf": 50,
    "feature_fraction": 0.8, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 1.0,
    "metric": "average_precision", "verbosity": -1, "seed": 42, "deterministic": True, "num_threads": 4,
}
MAX_ROUNDS, EARLY_STOP = 3000, 150


def b1_rule(df: pd.DataFrame) -> np.ndarray:
    return ((df["fc_hi_max"] >= 41) & ((df["age"] >= 60) | (df["on_diuretic"] > 0))).astype(float).to_numpy()


def b2_points(df: pd.DataFrame) -> np.ndarray:
    return ((df["triple_today"] > 0).astype(float) + (df["fc_hi_max"] >= 41).astype(float)
            + (df["egfr_baseline"] < 60).astype(float)).to_numpy()


def fit_b0(train: pd.DataFrame):
    m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
    m.fit(train[B0].fillna(train[B0].median()), train["y"].astype(int))
    return m


def fit_lgb(train: pd.DataFrame, es: pd.DataFrame, features: list[str], monotone: dict | None = None) -> lgb.Booster:
    params = dict(LGB_PARAMS)
    if monotone:
        params["monotone_constraints"] = [int(monotone.get(f, 0)) for f in features]
        params["monotone_constraints_method"] = "advanced"
    dtr = lgb.Dataset(train[features], train["y"].astype(int), free_raw_data=False)
    des = lgb.Dataset(es[features], es["y"].astype(int), reference=dtr, free_raw_data=False)
    return lgb.train(params, dtr, num_boost_round=MAX_ROUNDS, valid_sets=[des],
                     callbacks=[lgb.early_stopping(EARLY_STOP, verbose=False)])


class Calibrated:
    """A raw scorer plus an isotonic map fitted on the 2024 calibration split."""

    def __init__(self, name: str, features: list[str], raw_fn, iso: IsotonicRegression | None = None):
        self.name, self.features, self.raw_fn, self.iso = name, features, raw_fn, iso

    def raw(self, df: pd.DataFrame) -> np.ndarray:
        return np.asarray(self.raw_fn(df), dtype=float)

    def fit_calibration(self, cal: pd.DataFrame) -> Calibrated:
        self.iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(self.raw(cal),
                                                                                        cal["y"].astype(float))
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        r = self.raw(df)
        return self.iso.predict(r) if self.iso is not None else r

    def iso_json(self) -> dict:
        return {"x": [float(v) for v in self.iso.X_thresholds_], "y": [float(v) for v in self.iso.y_thresholds_]}


def train_all(df: pd.DataFrame) -> tuple[dict[str, Calibrated], dict]:
    """Fit every model on 2024 (train / early-stop / calibration splits). Returns models and fitted boosters."""
    tr, es, cal = (df[df["split"] == s] for s in ("train", "early_stop", "calibration"))
    boosters = {"M": fit_lgb(tr, es, list(CORE), CORE), "M_full": fit_lgb(tr, es, FULL),
                "B3": fit_lgb(tr, es, RAW)}
    b0 = fit_b0(tr)
    b0_med = tr[B0].median()
    models = {
        "B0_last_lab_logistic": Calibrated("B0", B0, lambda d: b0.predict_proba(d[B0].fillna(b0_med))[:, 1]),
        "B1_heat_index_rule": Calibrated("B1", ["fc_hi_max", "age", "on_diuretic"], b1_rule),
        "B2_triple_heat_egfr_points": Calibrated("B2", ["triple_today", "fc_hi_max", "egfr_baseline"], b2_points),
        "B3_lightgbm_raw": Calibrated("B3", RAW, lambda d: boosters["B3"].predict(d[RAW])),
        "B4_twin_physics_risk": Calibrated("B4", ["mc_risk_72h"], lambda d: d["mc_risk_72h"].to_numpy()),
        "M_hybrid_core25": Calibrated("M", list(CORE), lambda d: boosters["M"].predict(d[list(CORE)])),
        "M_full_sensitivity": Calibrated("M_full", FULL, lambda d: boosters["M_full"].predict(d[FULL])),
    }
    for m in models.values():
        m.fit_calibration(cal)
    return models, boosters


def save(models: dict[str, Calibrated], boosters: dict, thresholds: dict, out_dir: Path, regime: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for k, b in boosters.items():
        b.save_model(str(out_dir / f"fastclock_{k}_{regime}.txt"))
    meta = {name: {"features": m.features, "isotonic": m.iso_json()} for name, m in models.items()}
    (out_dir / f"fastclock_calibration_{regime}.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    (out_dir / f"thresholds_{regime}.json").write_text(json.dumps(thresholds, indent=2), encoding="utf-8")
