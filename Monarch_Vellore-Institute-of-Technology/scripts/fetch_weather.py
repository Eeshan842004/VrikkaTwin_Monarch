"""Download hourly heat-season weather (1 Mar - 30 Jun) for the 7 cohort cities from the Open-Meteo archive.

The 2024 season is the training season; 2025 and 2026 are held-out temporal test seasons (Decisions v1 item 15).
Output: data/weather/<year>/<City>.parquet (one row per hour, Asia/Kolkata time) + data/weather/ATTRIBUTION.md.
Data: Open-Meteo historical weather API (ERA5 reanalysis, ~25 km grid, Copernicus), licence CC BY 4.0. ERA5 smooths
peaks (lower than station readings) and has no urban heat island.

    python scripts/fetch_weather.py                 # all seasons
    python scripts/fetch_weather.py --years 2025
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import pandas as pd
import requests

from vrikka.config import DATA_DIR, REPORTS_DIR, load_yaml, settings

HOURLY = ["temperature_2m", "relative_humidity_2m", "apparent_temperature", "wind_speed_10m", "shortwave_radiation"]


def fetch_city(name: str, lat: float, lon: float, start: str, end: str) -> pd.DataFrame:
    params = {
        "latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
        "hourly": ",".join(HOURLY), "timezone": "Asia/Kolkata", "wind_speed_unit": "ms",
    }
    for attempt in range(4):
        try:
            r = requests.get(settings().openmeteo_base, params=params, timeout=60)
            r.raise_for_status()
            break
        except requests.RequestException as exc:
            if attempt == 3:
                raise
            print(f"  {name}: retry after {exc}", flush=True)
            time.sleep(5 * (attempt + 1))
    js = r.json()
    df = pd.DataFrame(js["hourly"])
    df["time"] = pd.to_datetime(df["time"])
    df.insert(0, "city", name)
    df["elevation_m"] = js.get("elevation")
    return df


SEASONS = {2024: "train", 2025: "held-out test", 2026: "held-out test"}


def fetch_season(year: int) -> tuple[dict, list[str]]:
    start, end = f"{year}-03-01", f"{year}-06-30"
    out_dir = DATA_DIR / "weather" / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {}
    print(f"== {year} season ({SEASONS[year]})", flush=True)
    for name, c in load_yaml("cities").items():
        df = fetch_city(name, c["lat"], c["lon"], start, end)
        missing = int(df[HOURLY].isna().sum().sum())
        df.to_parquet(out_dir / f"{name}.parquet", index=False)
        daily_max = df.set_index("time")["temperature_2m"].resample("D").max()
        summary[name] = {
            "rows": len(df), "missing_values": missing,
            "tmax_c": round(float(df["temperature_2m"].max()), 1),
            "tmax_date": str(df.loc[df["temperature_2m"].idxmax(), "time"].date()),
            "days_tmax_ge_40": int((daily_max >= 40).sum()),
            "rh_mean": round(float(df["relative_humidity_2m"].mean()), 1),
        }
        print(f"{name:10s} rows={len(df)} missing={missing} tmax={summary[name]['tmax_c']} °C "
              f"on {summary[name]['tmax_date']}  days>=40°C={summary[name]['days_tmax_ge_40']}", flush=True)
        time.sleep(1)
    expected = (pd.Timestamp(end) - pd.Timestamp(start)).days * 24 + 24
    bad = [k for k, v in summary.items() if v["rows"] != expected]
    return {"role": SEASONS[year], "period": [start, end], "cities": summary}, bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="*", type=int, choices=sorted(SEASONS), default=sorted(SEASONS))
    years = ap.parse_args().years
    (DATA_DIR / "weather").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "weather" / "ATTRIBUTION.md").write_text(
        "# Weather data attribution\n\nHourly weather for 1 March to 30 June of 2024 (training season), 2025 and "
        "2026 (held-out test seasons) from the "
        "[Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api), "
        "based on ERA5 reanalysis (Copernicus Climate Change Service). Licence: CC BY 4.0. "
        "Weather data by Open-Meteo.com. ERA5 is a ~25 km reanalysis: peaks are smoother (lower) than station "
        "readings and there is no urban heat island.\n", encoding="utf-8")
    inv = REPORTS_DIR / "data_inventory.json"
    data = json.loads(inv.read_text()) if inv.exists() else {}
    seasons = data.get("weather", {}).get("seasons", {})
    all_bad = []
    for year in years:
        seasons[str(year)], bad = fetch_season(year)
        all_bad += [f"{year}:{b}" for b in bad]
    data["weather"] = {"source": "Open-Meteo archive (ERA5)", "licence": "CC BY 4.0", "seasons": seasons}
    inv.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("\nall seasons complete" if not all_bad else f"\nROW-COUNT MISMATCH: {all_bad}")
    return 1 if all_bad else 0


if __name__ == "__main__":
    sys.exit(main())
