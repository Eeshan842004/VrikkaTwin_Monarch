"""Weather + daily routine -> hourly sweat for many people at once (master plan §7.1, §7.5, §9.2).

This module is neutral: the twin uses it with a person's *typical* routine and a *noisy forecast*; the ground-truth
simulator uses it with the archived weather and day-to-day routine jitter. It never sees hidden truth parameters.

Body size: PHS sweat scales mainly with body surface area, so we run PHS once per sex on a reference body
(women 55 kg / 1.52 m in sari or salwar clo 0.6; men 65 kg / 1.65 m in light cotton clo 0.5) and scale each person's
sweat by their BSA ratio (documented approximation; avoids building dozens of tables).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from vrikka.config import DATA_DIR, load_yaml, param
from vrikka.physiology.heat import SweatTable, load_sweat_table, met_for_occupation

REF_BODY = {True: (55.0, 1.52, "clo_sari_salwar"), False: (65.0, 1.65, "clo_light_cotton")}
ROOF_KEY = {"concrete": "indoor_offset_concrete_c", "tin_asbestos": "indoor_offset_tin_roof_c",
            "thatch": "indoor_offset_thatch_c"}


def load_season(year: int) -> dict[str, pd.DataFrame]:
    """City -> hourly archived weather (1 Mar - 30 Jun of ``year``). Neutral file reader used by twin and simulator."""
    return {c: pd.read_parquet(DATA_DIR / "weather" / str(year) / f"{c}.parquet") for c in load_yaml("cities")}


def bsa_mosteller(weight_kg, height_m):
    return np.sqrt(np.asarray(height_m) * 100 * np.asarray(weight_kg) / 3600)


def reference_tables() -> dict[bool, SweatTable]:
    return {female: load_sweat_table(w, h, param(clo)) for female, (w, h, clo) in REF_BODY.items()}


def occupation_routine() -> dict:
    return load_yaml("cohort")["occupation_routine"]


def _indoor_offset(roof: np.ndarray, cooling: np.ndarray) -> np.ndarray:
    off = np.array([param(ROOF_KEY[r]) for r in roof])
    off = np.where(cooling == "ac", param("indoor_offset_ac_c"), off)
    return np.where(cooling == "cooler", param("indoor_offset_cooler_c"), off)


def _hourly_block(weather: dict[str, pd.DataFrame], people: pd.DataFrame, cap_c: float | None = None,
                  sweat_mult: float = 1.0, extra_outdoor_h: np.ndarray | None = None,
                  tables: dict[bool, SweatTable] | None = None, chunk: int = 1_000_000,
                  start_hour: int = 0) -> dict:
    """One block of patients (float64); see :func:`cohort_hourly_sweat`."""
    tables = tables or reference_tables()
    cities = list(dict.fromkeys(people["city"]))
    any_w = weather[cities[0]]
    T, N = len(any_w), len(people)
    D = (T + start_hour + 23) // 24
    hour = (np.arange(T) + start_hour) % 24
    day = (np.arange(T) + start_hour) // 24
    sunday = (pd.to_datetime(any_w["time"]).dt.dayofweek.to_numpy() == 6)

    idx = np.array([cities.index(c) for c in people["city"]])
    stack = {k: np.stack([weather[c][k].to_numpy(dtype=float) for c in cities]) for k in
             ("temperature_2m", "relative_humidity_2m", "shortwave_radiation")}
    tdb_out = stack["temperature_2m"][idx].T                       # (T, N)
    if cap_c is not None:
        tdb_out = np.minimum(tdb_out, cap_c)
    rh = stack["relative_humidity_2m"][idx].T
    sw = stack["shortwave_radiation"][idx].T

    lag = int(param("indoor_lag_h"))
    lagged = np.vstack([np.repeat(tdb_out[:1], lag, axis=0), tdb_out[:-lag]]) if lag else tdb_out
    tdb_in = lagged + _indoor_offset(people["roof"].to_numpy(), people["cooling"].to_numpy())[None, :]

    start = people["outdoor_start"].to_numpy(dtype=float)[None, :]
    hours = np.broadcast_to(people["outdoor_hours"].to_numpy(dtype=float), (D, N)).copy()
    if extra_outdoor_h is not None:
        hours = np.clip(hours + extra_outdoor_h, 0, 12)
    hours_t = hours[day]                                            # (T, N)
    workday = ~sunday[:, None] | people["works_sunday"].to_numpy(dtype=bool)[None, :]
    outdoors = (hour[:, None] >= start) & (hour[:, None] < start + hours_t) & workday

    occ = people["occupation"].to_numpy()
    met_out = np.array([met_for_occupation(o) for o in occ])[None, :]
    at_office = (occ == "office")[None, :] & (hour[:, None] >= 10) & (hour[:, None] < 18) & workday
    met_in = np.where(at_office, param("met_office"), param("met_home"))
    tdb = np.where(outdoors, tdb_out, np.where(at_office, lagged + param("indoor_offset_ac_c"), tdb_in))
    met = np.where(outdoors, met_out, met_in)
    dtr = np.where(outdoors, param("tr_offset_sun_c") * sw / 800.0, 0.0)

    sweat = np.empty((T, N))
    valid = np.empty((T, N), dtype=bool)
    female = people["female"].to_numpy(dtype=bool)
    bsa_ratio = np.empty(N)
    for sex in (True, False):
        cols = np.where(female == sex)[0]
        if cols.size == 0:
            continue
        w_ref, h_ref, _ = REF_BODY[sex]
        bsa_ratio[cols] = bsa_mosteller(people["weight_kg"].to_numpy()[cols], people["height_m"].to_numpy()[cols]) \
            / bsa_mosteller(w_ref, h_ref)
        flat = [a[:, cols].ravel() for a in (tdb, rh, met, dtr)]
        out_s, out_v = np.empty(flat[0].size), np.empty(flat[0].size, dtype=bool)
        for i in range(0, flat[0].size, chunk):
            s, v = tables[sex].rate(*(f[i:i + chunk] for f in flat))
            out_s[i:i + chunk], out_v[i:i + chunk] = s, v
        sweat[:, cols] = out_s.reshape(T, cols.size)
        valid[:, cols] = out_v.reshape(T, cols.size)
    sweat = np.clip(sweat * bsa_ratio[None, :] * sweat_mult, 0.0, param("sweat_cap_l_h"))
    return {"sweat_l_h": sweat, "valid": valid, "outdoors": outdoors, "tdb_exposure": tdb, "met": met}


def cohort_hourly_sweat(weather: dict[str, pd.DataFrame], people: pd.DataFrame, cap_c: float | None = None,
                        sweat_mult: float = 1.0, extra_outdoor_h: np.ndarray | None = None,
                        tables: dict[bool, SweatTable] | None = None, chunk: int = 1_000_000,
                        start_hour: int = 0, patient_chunk: int = 1000) -> dict:
    """Hourly sweat (L/h), metabolic rate (met) and exposure for every person: arrays of shape (T, N).

    ``people`` needs: city, female, weight_kg, height_m, occupation, outdoor_start, outdoor_hours, works_sunday,
    roof, cooling. ``weather`` maps city -> hourly frame (same timestamps for all cities); ``start_hour`` is the clock
    hour of its first row (the twin's days start at 08:00).
    ``cap_c`` caps outdoor air temperature (heat counterfactual); ``extra_outdoor_h`` (D, N) adds/removes outdoor
    hours per day (routine jitter, simulator only).

    Patients are processed ``patient_chunk`` at a time and the (T, N) arrays are returned as float32 (sweat_l_h,
    tdb_exposure, met) and bool (valid, outdoors), so a 10,000-patient season needs about 0.4 GB instead of several GB.
    ``met`` is the hourly metabolic rate in met units (outdoors: the occupation's work met; otherwise home / office).
    """
    tables = tables or reference_tables()
    n = len(people)
    parts = []
    for i in range(0, n, patient_chunk):
        sl = slice(i, min(i + patient_chunk, n))
        extra = None if extra_outdoor_h is None else extra_outdoor_h[:, sl]
        blk = _hourly_block(weather, people.iloc[sl], cap_c, sweat_mult, extra, tables, chunk, start_hour)
        parts.append({k: (v.astype(np.float32) if v.dtype == np.float64 else v) for k, v in blk.items()})
    return {k: np.concatenate([p[k] for p in parts], axis=1) for k in parts[0]}


def noisy_forecast(daily_tmax: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Forecast error for days +1..+3 (registry SDs 1.0 / 1.5 / 2.0 degC). Features never use the archived truth."""
    sd = np.array([param("forecast_sd_day1_c"), param("forecast_sd_day2_c"), param("forecast_sd_day3_c")])
    return daily_tmax + rng.normal(0.0, sd[: daily_tmax.shape[-1]], size=daily_tmax.shape)


def forecast_weather(weather: pd.DataFrame, issue_hour: int, horizon_h: int, rng: np.random.Generator) -> pd.DataFrame:
    """Hourly forecast for the next ``horizon_h`` hours issued at ``issue_hour``: the archived values plus a smooth
    per-day temperature error (SD growing 1.0 -> 2.0 degC) and a relative humidity error (registry)."""
    w = weather.iloc[issue_hour:issue_hour + horizon_h].copy()
    lead_day = np.minimum(np.arange(len(w)) // 24, 2)
    sd = np.array([param("forecast_sd_day1_c"), param("forecast_sd_day2_c"), param("forecast_sd_day3_c")])
    err_t = rng.normal(0.0, sd)[lead_day]
    err_rh = rng.normal(0.0, param("forecast_rh_rel_sd"), 3)[lead_day]
    w["temperature_2m"] = w["temperature_2m"].to_numpy() + err_t
    w["relative_humidity_2m"] = np.clip(w["relative_humidity_2m"].to_numpy() * (1 + err_rh), 1, 100)
    return w
