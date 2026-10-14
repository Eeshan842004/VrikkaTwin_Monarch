"""Download hourly 2024 heat-season weather for the 7 cohort cities from the Open-Meteo archive (§7.5, §24).

Output: data/weather/<City>.parquet (one row per hour, Asia/Kolkata time) + data/weather/ATTRIBUTION.md.
Data: Open-Meteo historical weather API (ERA5 reanalysis, Copernicus), licence CC BY 4.0.
"""
from __future__ import annotations

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


def main() -> int:
    cohort = load_yaml("cohort")
    start, end = str(cohort["season"]["start"]), str(cohort["season"]["end"])
    out_dir = DATA_DIR / "weather"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {}
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
    (out_dir / "ATTRIBUTION.md").write_text(
        "# Weather data attribution\n\nHourly weather for 2024-03-01 to 2024-06-30 from the "
        "[Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api), "
        "based on ERA5 reanalysis (Copernicus Climate Change Service). Licence: CC BY 4.0. "
        "Weather data by Open-Meteo.com.\n", encoding="utf-8")
    inv = REPORTS_DIR / "data_inventory.json"
    data = json.loads(inv.read_text()) if inv.exists() else {}
    data["weather"] = {"source": "Open-Meteo archive (ERA5)", "licence": "CC BY 4.0", "period": [start, end],
                       "cities": summary}
    inv.write_text(json.dumps(data, indent=2), encoding="utf-8")
    expected = (pd.Timestamp(end) - pd.Timestamp(start)).days * 24 + 24
    bad = [k for k, v in summary.items() if v["rows"] != expected]
    print(f"\nexpected {expected} rows per city; {'all OK' if not bad else 'MISMATCH: ' + str(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
