"""R4 (new job): real day-to-day resting-HR noise from PMData's RAW Fitbit heart-rate stream (Decisions v2 A-5a).

Method (exactly as decided):
1. Our own daily resting HR = lowest 30-minute rolling mean between 00:00 and 06:00 local time, only on nights with
   >= 4 h of HR data (Fitbit's smoothed ``resting_heart_rate`` value is NOT used).
2. Per person: SD of (daily resting HR - that person's rolling 7-day median). People need >= 30 valid nights.
3. Median across people -> sigma_hr = max(that, 3 bpm). If fewer than 8 people qualify, keep 4 bpm (ASSUMPTION).
Weight: PMData weight is self-reported, mostly whole kilograms -> not used for sigma_weight (reported only).
Writes reports/pmdata_noise.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from vrikka.config import DATA_DIR, REPORTS_DIR

ROOT = DATA_DIR / "raw" / "pmdata"
MIN_NIGHT_MIN, MIN_NIGHTS, MIN_PEOPLE, FLOOR = 240, 30, 8, 3.0


def nightly_rhr(path: Path) -> pd.Series:
    raw = json.loads(path.read_text(encoding="utf-8"))
    df = pd.DataFrame({"t": [r["dateTime"] for r in raw], "bpm": [r["value"]["bpm"] for r in raw]})
    del raw
    df["t"] = pd.to_datetime(df["t"])
    df = df[(df["bpm"] >= 30) & (df["bpm"] <= 220) & (df["t"].dt.hour < 6)]
    minute = df.set_index("t")["bpm"].resample("1min").mean()
    out = {}
    for night, s in minute.groupby(minute.index.date):
        if s.notna().sum() < MIN_NIGHT_MIN:
            continue
        roll = s.rolling(30, min_periods=20).mean()
        if roll.notna().any():
            out[pd.Timestamp(night)] = float(roll.min())
    return pd.Series(out).sort_index()


def main() -> int:
    people = {}
    for f in sorted(ROOT.glob("p*/fitbit/heart_rate.json")):
        pid = f.parts[-3]
        rhr = nightly_rhr(f)
        if len(rhr) == 0:
            continue
        med7 = rhr.asfreq("D").rolling(7, center=True, min_periods=4).median().reindex(rhr.index)
        resid = (rhr - med7).dropna()
        people[pid] = {
            "valid_nights": int(len(rhr)),
            "median_rhr": round(float(rhr.median()), 1),
            "sd_vs_7day_median": round(float(resid.std()), 3),
            "qualifies": len(rhr) >= MIN_NIGHTS,
        }
        print(pid, people[pid], flush=True)
    q = [v["sd_vs_7day_median"] for v in people.values() if v["qualifies"]]
    if len(q) >= MIN_PEOPLE:
        med = float(np.median(q))
        sigma, prov = max(med, FLOOR), "CITED"
    else:
        med, sigma, prov = None, 4.0, "ASSUMPTION"
    res = {
        "method": "lowest 30-min rolling mean HR 00:00-06:00 (>= 4 h data); SD vs rolling 7-day median; median "
        "across people with >= 30 nights; floor 3 bpm (Decisions v2 A-5a)",
        "people_downloaded": len(people),
        "people_qualifying": len(q),
        "median_sd_bpm": round(med, 3) if med else None,
        "sigma_hr_bpm": round(sigma, 2),
        "provenance": prov,
        "floor_applied": bool(med is not None and med < FLOOR),
        "people": people,
    }
    (REPORTS_DIR / "pmdata_noise.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "people"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
