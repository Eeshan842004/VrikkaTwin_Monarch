"""R4 (secondary line, Amendment 1 A1.7): does the twin + frozen hybrid model M raise red alerts on healthy real people?

    python scripts/validate_r4.py          # needs data/raw/pmdata (scripts/download_public_data.py --only pmdata)

PMData (Thambawita et al. 2020, CC BY 4.0): 16 healthy adults in Norway, Nov 2019 - Mar 2020, with Fitbit's daily
resting heart rate and self-reported morning weight. Nobody here is on kidney-relevant medicines, ill (as recorded) or
in heat, so every red alert would be a FALSE alarm caused by real-world measurement noise. Target ~0.

Method (nothing is tuned): the same batched twin and 25 core features as the fast clock (twin/batch_ukf.py,
fastclock/features.py), the frozen M model, its frozen isotonic map and thresholds (mismatched regime) and the same
hysteresis / de-duplication. Inputs that PMData does not have are set as for a person who reports nothing: no
symptoms, tablets or ORS; no medicines; no lab, so the §9.3 rule back-calculates the baseline creatinine from
``baseline_egfr_fallback``; SBP not recorded (missing channel). Exposure: real Oslo weather (Open-Meteo archive) with
the office routine and a noisy 72-h forecast, exactly as in the cohort. Caveats: Fitbit's resting HR is smoothed (less
noisy than our own nightly value, see reports/pmdata_noise.json) and weight is self-reported in whole kilograms.
Writes reports/r4_pmdata.json.
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd
import requests

from vrikka.config import DATA_DIR, REPORTS_DIR, SEED, load_yaml, param, settings
from vrikka.fastclock import frozen
from vrikka.fastclock.alerts import RED, alert_states, rates
from vrikka.fastclock.features import CORE
from vrikka.physiology.equations import creatinine_from_egfr
from vrikka.physiology.exposure import cohort_hourly_sweat, forecast_weather
from vrikka.physiology.renal import Params
from vrikka.twin.batch_ukf import BatchTwin

ROOT = DATA_DIR / "raw" / "pmdata"
START, END = "2019-11-01", "2020-03-31"
OSLO = (59.91, 10.75)
REGIME = "mismatched"


def oslo_weather() -> pd.DataFrame:
    f = ROOT / "oslo_weather.parquet"
    if f.exists():
        return pd.read_parquet(f)
    end = (pd.Timestamp(END) + pd.Timedelta(days=4)).date().isoformat()
    r = requests.get(settings().openmeteo_base, timeout=120, params={
        "latitude": OSLO[0], "longitude": OSLO[1], "start_date": START, "end_date": end, "timezone": "Europe/Oslo",
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,shortwave_radiation", "wind_speed_unit": "ms"})
    r.raise_for_status()
    h = r.json()["hourly"]
    w = pd.DataFrame(h).rename(columns={"time": "time"})
    w["time"] = pd.to_datetime(w["time"])
    w.to_parquet(f, index=False)
    return w


def people_frame() -> pd.DataFrame:
    ov = pd.read_excel(ROOT / "participant-overview.xlsx", header=1)
    ov = ov.rename(columns={"Participant ID": "pid", "Age": "age", "Height": "height_cm", "Gender": "gender"})
    ov = ov[ov["pid"].astype(str).str.match(r"p\d\d")]
    ov["female"] = ov["gender"].astype(str).str.strip().str.lower().str.startswith("f")
    return ov[["pid", "age", "height_cm", "female"]].reset_index(drop=True)


def series(pid: str, dates: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    rhr = pd.Series(dtype=float)
    f = ROOT / pid / "fitbit" / "resting_heart_rate.json"
    if f.exists():
        raw = json.loads(f.read_text(encoding="utf-8"))
        rhr = pd.Series({pd.Timestamp(r["dateTime"]).normalize(): r["value"]["value"] for r in raw}, dtype=float)
        rhr = rhr[rhr > 0]
    wt = pd.Series(dtype=float)
    g = ROOT / pid / "googledocs" / "reporting.csv"
    if g.exists():
        rep = pd.read_csv(g)
        rep["d"] = pd.to_datetime(rep["date"], format="%d/%m/%Y", errors="coerce")
        rep = rep.dropna(subset=["d"]).groupby("d")["weight"].last()
        wt = pd.to_numeric(rep, errors="coerce").dropna()
    return rhr.reindex(dates).to_numpy(float), wt.reindex(dates).to_numpy(float)


def main() -> int:
    if not (ROOT / "participant-overview.xlsx").exists():
        print("missing PMData; run scripts/download_public_data.py --only pmdata")
        return 1
    dates = pd.date_range(START, END, freq="D")
    D = len(dates)
    ppl = people_frame()
    hr, wt = zip(*(series(p, dates) for p in ppl["pid"]), strict=True)
    HR, WT = np.array(hr).T, np.array(wt).T                                  # (D, N)
    keep = (np.isfinite(HR).sum(0) >= 14) & (np.isfinite(WT).sum(0) >= 5)
    ppl, HR, WT = ppl[keep].reset_index(drop=True), HR[:, keep], WT[:, keep]
    N = len(ppl)
    w = oslo_weather()
    weather = {"Oslo": w.iloc[: (D + 4) * 24].reset_index(drop=True)}
    routine = load_yaml("cohort")["occupation_routine"]["office"]
    dry = np.nanmedian(WT, axis=0)
    people = pd.DataFrame({"city": "Oslo", "female": ppl["female"], "weight_kg": dry,
                           "height_m": ppl["height_cm"] / 100.0, "occupation": "office", "roof": "concrete",
                           "cooling": "none", "outdoor_start": routine["outdoor_start"],
                           "outdoor_hours": routine["outdoor_hours"], "works_sunday": False})
    egfr0 = param("baseline_egfr_fallback")
    base = np.array([creatinine_from_egfr(egfr0, a, f) for a, f in zip(ppl["age"], ppl["female"], strict=True)])
    ps = [Params.from_patient(age=float(a), female=bool(f), weight_kg=float(m), egfr=egfr0, height_m=float(h) / 100,
                              cr_base=float(b))
          for a, f, m, h, b in zip(ppl["age"], ppl["female"], dry, ppl["height_cm"], base, strict=True)]
    hr_base = np.array([np.median(HR[np.isfinite(HR[:, i]), i][:28]) for i in range(N)])   # first 28 readings
    twin = BatchTwin(ps, hr_base, np.zeros(N), np.zeros(N, dtype=bool), base)
    ex = cohort_hourly_sweat(weather, people)
    sweat_h, met_h = ex["sweat_l_h"], ex["met"]
    tmax = w["temperature_2m"].to_numpy(float)[: (D + 4) * 24].reshape(-1, 24).max(axis=1)
    rng = np.random.default_rng(SEED)
    n_draws = int(param("mc_draws_training"))
    feats = {f: np.zeros((D, N)) for f in CORE}
    streak = np.zeros(D)
    for d in range(1, D):
        streak[d] = streak[d - 1] + 1 if tmax[d - 1] >= param("hot_day_tmax_c") else 0
    twin._start_eff({})
    for d in range(D):
        if d > 0:
            a, b = (d - 1) * 24 + 8, d * 24 + 8
            twin.predict({"sweat_l_h": sweat_h[a:b], "met": met_h[a:b]})
        twin.update(np.column_stack([WT[d], HR[d], np.full(N, np.nan)]), np.zeros(N))
        fw = forecast_weather(weather["Oslo"], d * 24 + 8, 72, rng)
        fx = cohort_hourly_sweat({"Oslo": fw}, people, start_hour=8)
        r = twin.risk_72h({"sweat_l_h": fx["sweat_l_h"], "met": fx["met"]}, base, n_draws, rng)
        f = feats
        f["mc_risk_72h"][d], f["mc_cr_peak_ratio"][d], f["mc_gfr_min_frac"][d] = r["risk"], r["cr_peak_ratio"], \
            r["gfr_min_frac"]
        f["tw_cr_ratio"][d] = twin.x[:, 2] / base
        f["tw_v_ecf"][d] = twin.x[:, 1]
        f["tw_v_ecf_sd"][d] = np.sqrt(np.maximum(twin.P[:, 1, 1], 0))
        f["tw_gfr_frac"][d] = twin.gfr_frac_now()
        f["tw_theta"][d] = twin.theta
        f["fc_sweat_72h"][d] = fx["sweat_l_h"].astype(float).sum(axis=0)
        f["fc_tmax_72h"][d] = fw["temperature_2m"].max()
        f["hot_streak_days"][d] = streak[d]
        f["age"][d], f["egfr_baseline"][d] = ppl["age"].to_numpy(float), egfr0
        f["wt_vs_dry_kg"][d] = WT[d] - dry
        f["hr_delta_bpm"][d] = HR[d] - hr_base
    X = pd.DataFrame({k: v.T.ravel() for k, v in feats.items()})[list(CORE)]
    thr = frozen.thresholds(REGIME)["M_hybrid_core25"]
    prob = frozen.predict(X, "M_hybrid_core25", REGIME).reshape(N, D)
    observed = (np.isfinite(HR) | np.isfinite(WT)).T                        # (N, D)
    first, last = observed.argmax(1), D - 1 - observed[:, ::-1].argmax(1)
    elig = np.zeros((N, D), dtype=bool)
    for i in range(N):
        elig[i, first[i]:last[i] + 1] = True
    st = alert_states(prob, elig, thr["red_threshold"], thr["amber_threshold"])
    red, tot = rates(st, elig)
    mc = feats["mc_risk_72h"].T
    lv = load_yaml("alert_policy")["levels"]
    out = {
        "check": "R4 (secondary sanity line; Amendment 1 A1.7). Healthy real people: every red alert is a false alarm.",
        "dataset": "PMData (Thambawita et al., MMSys 2020; CC BY 4.0): Fitbit daily resting HR + self-reported weight",
        "people": int(N), "patient_days": int(elig.sum()), "period": [START, END],
        "days_with_weight": int(np.isfinite(WT).sum()), "days_with_resting_hr": int(np.isfinite(HR).sum()),
        "model": f"frozen hybrid model M ({REGIME}), frozen isotonic map and thresholds; nothing refitted",
        "red_notifications_per_100_patient_days": round(red, 3),
        "amber_plus_red_notifications_per_100_patient_days": round(tot, 3),
        "red_days_per_100_patient_days": round(100 * float(((st["level"] == RED) & elig).sum()) / elig.sum(), 3),
        "people_with_any_red": int(((st["level"] == RED) & elig).any(axis=1).sum()),
        "max_calibrated_probability": round(float(prob[elig].max()), 5),
        "red_threshold": thr["red_threshold"],
        "twin_simulation_risk": {"max": round(float(mc[elig].max()), 3),
                                 "share_of_days_at_or_above_display_red_band": round(float(
                                     (mc[elig] >= lv["amber"]["max_prob"]).mean()), 4),
                                 "share_of_days_at_or_above_display_amber_band": round(float(
                                     (mc[elig] >= lv["green"]["max_prob"]).mean()), 4)},
        "assumptions": {"baseline": "no lab: creatinine back-calculated from baseline_egfr_fallback (§9.3 rule)",
                        "egfr_baseline_feature": egfr0, "routine": "office", "weather": "Oslo, Open-Meteo archive",
                        "sbp": "not recorded (missing channel)",
                        "hr_base": "median of the first 28 resting-HR readings"},
        "caveats": "Fitbit's daily resting HR is smoothed (day-to-day SD lower than our nightly value); weight is "
                   "self-reported in whole kilograms; Norwegian winter, so heat never drives risk here.",
    }
    (REPORTS_DIR / "r4_pmdata.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
