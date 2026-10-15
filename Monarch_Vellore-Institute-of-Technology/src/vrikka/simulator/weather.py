"""Weather replay for the synthetic seasons (master plan §7.5; Decisions v1 item 15).

2024 = training season; 2025 and 2026 = held-out temporal test seasons (same patients, new weather).
"""
from __future__ import annotations

import pandas as pd

from vrikka.physiology.exposure import load_season  # noqa: F401  (neutral reader, re-exported)

SEASON_ROLE = {2024: "train", 2025: "test", 2026: "test"}


def daily_tmax(weather: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Days x cities table of daily maximum air temperature."""
    return pd.DataFrame({c: w.set_index("time")["temperature_2m"].resample("D").max() for c, w in weather.items()})
