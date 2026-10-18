"""The frozen Part 4 fast clock: load the saved LightGBM models, isotonic maps and alert thresholds, and score / explain
with them. Nothing here fits anything; everything after Part 4 (triage panel, R4, evaluation extras, the app) scores
through this one module, so the same frozen model is used everywhere.

Scripts import this module rather than lightgbm directly, so ``vrikka/__init__`` has preloaded a current MSVC runtime
before LightGBM loads (see there).
"""
from __future__ import annotations

import json
from functools import lru_cache

import lightgbm as lgb
import numpy as np
import pandas as pd

from vrikka.config import MODELS_DIR
from vrikka.fastclock.explain import top_reasons

BOOSTER_OF = {"M_hybrid_core25": "M", "M_full_sensitivity": "M_full", "B3_lightgbm_raw": "B3"}


@lru_cache(maxsize=8)
def booster(model: str = "M_hybrid_core25", regime: str = "mismatched") -> lgb.Booster:
    return lgb.Booster(model_file=str(MODELS_DIR / f"fastclock_{BOOSTER_OF[model]}_{regime}.txt"))


@lru_cache(maxsize=4)
def calibration(regime: str = "mismatched") -> dict:
    return json.loads((MODELS_DIR / f"fastclock_calibration_{regime}.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def thresholds(regime: str = "mismatched") -> dict:
    return json.loads((MODELS_DIR / f"thresholds_{regime}.json").read_text(encoding="utf-8"))


def features(model: str = "M_hybrid_core25", regime: str = "mismatched") -> list[str]:
    return calibration(regime)[model]["features"]


def calibrate(model: str, raw: np.ndarray, regime: str = "mismatched") -> np.ndarray:
    """Frozen isotonic map (sklearn IsotonicRegression with out_of_bounds='clip' is a clipped linear interpolation)."""
    iso = calibration(regime)[model]["isotonic"]
    return np.interp(np.asarray(raw, dtype=float), iso["x"], iso["y"])


def predict(X: pd.DataFrame, model: str = "M_hybrid_core25", regime: str = "mismatched") -> np.ndarray:
    """Calibrated probability from a LightGBM model (M, M_full or B3) or B4 (the twin's Monte-Carlo risk)."""
    if model == "B4_twin_physics_risk":
        return calibrate(model, X["mc_risk_72h"].to_numpy(float), regime)
    return calibrate(model, booster(model, regime).predict(X[features(model, regime)]), regime)


def reasons(X: pd.DataFrame, k: int = 3, model: str = "M_hybrid_core25", regime: str = "mismatched") -> list:
    return top_reasons(booster(model, regime), X[features(model, regime)], k)
