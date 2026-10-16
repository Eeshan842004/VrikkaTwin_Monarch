"""Why this risk: LightGBM's native per-prediction contributions (``pred_contrib``) -> top-3 reasons -> i18n keys
(master plan §12.6). Only features that push the risk UP are shown as reasons; each maps to ``reason.<feature>`` in
config/i18n/<lang>.yaml (EN / HI / KN / TE)."""
from __future__ import annotations

import lightgbm as lgb
import numpy as np
import pandas as pd


def top_reasons(booster: lgb.Booster, X: pd.DataFrame, k: int = 3) -> list[list[dict]]:
    contrib = booster.predict(X, pred_contrib=True)            # (n, n_features + 1); last column = bias
    names = booster.feature_name()
    out = []
    for row in contrib[:, :-1]:
        order = np.argsort(-row)
        out.append([{"feature": names[j], "i18n_key": f"reason.{names[j]}", "contribution": float(row[j])}
                    for j in order[:k] if row[j] > 0])
    return out
