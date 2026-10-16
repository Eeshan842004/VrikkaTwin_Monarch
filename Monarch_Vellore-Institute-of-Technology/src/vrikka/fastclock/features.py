"""Fast-clock features: one row per patient-day at 09:00, from OBSERVED data only (master plan §12.2; Amendment 2 A2.6).

Inputs the builder may read: the public EHR columns (never ``true_*``), the patient's reported symptoms / tablets /
ORS, device readings, lab results, the archived city weather up to now with the patient's TYPICAL routine, and a NOISY
72-hour city forecast. The ground-truth columns (``y``, ``excluded``, ``onset``, ``episode_start``, ``stage``) are
attached for evaluation only and are never features (``tests/test_fastclock.py`` checks this).

Daily cycle per patient (all patients of a shard at once, :class:`vrikka.twin.batch_ukf.BatchTwin`):
08:00 morning readings -> UKF update (+ lab update if a lab was drawn) -> 09:00 features and the 72-hour Monte-Carlo
risk on the noisy forecast with today's reports "continuing as is" -> next day's predict (24 h of reported exposures).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from vrikka.config import load_yaml, param
from vrikka.physiology.exposure import cohort_hourly_sweat, forecast_weather
from vrikka.physiology.heat import heat_index_noaa, wet_bulb_stull
from vrikka.physiology.pk_nsaid import nsaid_units_per_day
from vrikka.physiology.renal import Params
from vrikka.twin.batch_ukf import BatchTwin

# Core set for the hybrid model M (<= 25 features, Amendment 2 A2.6) with LightGBM monotone constraints
# (+1 = risk can only rise with the feature, -1 = only fall, 0 = free).
CORE = {
    "mc_risk_72h": 1, "tw_cr_ratio": 1, "tw_v_ecf": 1, "tw_v_ecf_sd": 0, "tw_gfr_frac": -1, "mc_cr_peak_ratio": 1,
    "mc_gfr_min_frac": -1, "tw_theta": 0, "fc_sweat_72h": 1, "fc_tmax_72h": 1, "hot_streak_days": 1,
    "rep_fever_c": 1, "rep_gi_episodes": 1, "rep_poor_intake": 1, "rep_ors_l": -1, "nsaid_units_7d": 1,
    "nsaid_today": 1, "on_ras": 1, "on_diuretic": 1, "triple_today": 1, "age": 1, "egfr_baseline": -1,
    "heart_failure": 0, "wt_vs_dry_kg": -1, "hr_delta_bpm": 1,
}
TWIN = ["mc_risk_72h", "tw_cr_ratio", "tw_v_ecf", "tw_v_ecf_sd", "tw_gfr_frac", "mc_cr_peak_ratio", "mc_gfr_min_frac",
        "tw_theta", "tw_v_tot", "tw_cr_sd"]
EXTRA = ["tw_v_tot", "tw_cr_sd", "fc_hi_max", "fc_wetbulb_max", "night_min_c", "tmax_yesterday", "outdoor_hours",
         "outdoor_worker", "roof_tin", "cooling_none", "sweat_24h", "wt_delta_1d", "sbp_delta", "steps", "sleep_h",
         "skin_temp_delta", "band_missing", "rep_vomit", "rep_diarrhoea", "on_mra", "on_sglt2i", "on_metformin",
         "loop_diuretic", "beta_blocker", "female", "uacr_mg_g", "dm", "htn", "ckd_g3", "cyp2c9_as", "bmi",
         "days_since_lab", "last_lab_cr_ratio", "lab_today", "tier_code", "city_code"]
FULL = list(CORE) + [f for f in EXTRA if f not in CORE]
RAW = [f for f in FULL if f not in TWIN]                 # B3: plain LightGBM on raw inputs, no twin
B0 = ["last_lab_cr_ratio", "days_since_lab", "egfr_baseline"]
ID_COLS = ["patient_id", "season", "day", "pool", "regime"]
LABEL_COLS = ["y", "excluded", "onset", "episode_start", "stage"]
CITY_CODE = {c: i for i, c in enumerate(load_yaml("cities"))}
TIER_CODE = {"T0": 0, "T1": 1, "T2": 2}
SPLITS = (("train", 0.60), ("early_stop", 0.10), ("calibration", 0.15), ("internal_test", 0.15))


def assign_split(ids: np.ndarray, seed: int = 42) -> pd.Series:
    """Patient-level split of the 2024 training pool (Amendment 2 A2.3): every day of a patient is in one split."""
    rng = np.random.default_rng(seed + 404)
    order = rng.permutation(len(ids))
    cuts = np.cumsum([int(round(f * len(ids))) for _, f in SPLITS])
    lab = np.empty(len(ids), dtype=object)
    start = 0
    for (name, _), end in zip(SPLITS, cuts, strict=True):
        lab[order[start:end]] = name
        start = end
    lab[order[start:]] = SPLITS[-1][0]
    return pd.Series(lab, index=ids)


def lab_baselines(people: pd.DataFrame, labs: pd.DataFrame) -> np.ndarray:
    """§9.3 baseline from the two stable pre-season labs (mean of the last 2 within 365 days), vectorised."""
    pre = labs[labs["reason"] == "pre_season"].sort_values(["patient_id", "day"])
    last2 = pre.groupby("patient_id").tail(2).groupby("patient_id")["creatinine_mg_dl"].mean()
    out = people["patient_id"].map(last2)
    if out.isna().any():
        raise ValueError("every patient needs two pre-season labs for the §9.3 baseline")
    return out.to_numpy(dtype=float)


def daily_pivot(obs: pd.DataFrame, col: str, ids: pd.Index, D: int, fill=np.nan) -> np.ndarray:
    """Long (patient_id, day, col) -> (D, N) in the order of ``ids``."""
    w = obs.pivot(index="day", columns="patient_id", values=col).reindex(index=range(D), columns=ids)
    return w.to_numpy(dtype=float, na_value=fill)


def city_weather_features(weather: dict[str, pd.DataFrame], D: int) -> dict[str, pd.DataFrame]:
    """Archived (past) city weather known at 09:00 on day d: yesterday's max, last night's min, hot-day streak."""
    out = {}
    for c, w in weather.items():
        t = w["temperature_2m"].to_numpy(dtype=float)[: D * 24].reshape(D, 24)
        tmax = t.max(axis=1)
        streak = np.zeros(D)
        for d in range(1, D):
            streak[d] = streak[d - 1] + 1 if tmax[d - 1] >= 40.0 else 0
        out[c] = pd.DataFrame({"tmax_yesterday": np.r_[np.nan, tmax[:-1]], "night_min_c": t[:, :8].min(axis=1),
                               "hot_streak_days": streak})
    return out


def forecasts(weather: dict[str, pd.DataFrame], D: int, seed: int) -> list[dict[str, pd.DataFrame]]:
    """Noisy 72-hour city forecast issued at 09:00 (= after the 08:00 hour) every day; padded at the season end."""
    out = []
    for d in range(D):
        rng = np.random.default_rng(seed + d)
        day = {}
        for c, w in weather.items():
            f = forecast_weather(w, d * 24 + 8, 72, rng)
            if len(f) < 72:
                f = pd.concat([f, f.iloc[[-1] * (72 - len(f))]], ignore_index=True)
                f["time"] = pd.date_range(f["time"].iloc[0], periods=72, freq="h")
            day[c] = f.reset_index(drop=True)
        out.append(day)
    return out


def twin_params(people: pd.DataFrame, baseline: np.ndarray) -> list[Params]:
    def diu(v):
        return v if isinstance(v, str) and v else None
    return [Params.from_patient(age=r.age, female=r.female, weight_kg=r.weight_kg, egfr=r.egfr_baseline,
                                height_m=r.height_m, cr_base=float(b), diuretic=diu(r.diuretic),
                                water_at_work=r.water_access_at_work)
            for r, b in zip(people.itertuples(index=False), baseline, strict=True)]


def build_shard(people: pd.DataFrame, obs: pd.DataFrame, labs: pd.DataFrame, truth: pd.DataFrame,
                weather: dict[str, pd.DataFrame], fc: list[dict], season: int, regime: str, n_draws: int,
                rng: np.random.Generator, tables=None) -> pd.DataFrame:
    """Feature rows for one shard of patients over one season (see module docstring)."""
    people = people.reset_index(drop=True)
    ids = pd.Index(people["patient_id"])
    N = len(people)
    D = len(fc)
    c = load_yaml("cohort")
    baseline = lab_baselines(people, labs)
    ps = twin_params(people, baseline)
    twin = BatchTwin(ps, people["hr_base"].to_numpy(float), people["sbp_base"].to_numpy(float),
                     people["beta_blocker"].to_numpy(bool), baseline)

    # ---- typical-routine exposure on archived weather (hours since midnight of day 0)
    ex = cohort_hourly_sweat(weather, people, tables=tables)
    sweat_h, met_h = ex["sweat_l_h"], ex["met"]

    # ---- reported events -> hourly twin inputs (midnight grid, like the world)
    ob = obs[obs["patient_id"].isin(ids)]
    g = {k: daily_pivot(ob, k, ids, D, 0.0) for k in ("rep_fever_excess_c", "rep_vomit_episodes",
                                                     "rep_diarrhoea_episodes", "rep_ors_l_day")}
    poor = daily_pivot(ob.assign(p=ob["rep_poor_intake"].astype(float)), "p", ids, D, 0.0)
    nsaid_on = daily_pivot(ob.assign(p=ob["rep_nsaid_on"].astype(float)), "p", ids, D, 0.0) > 0
    gen = ob.pivot(index="day", columns="patient_id", values="rep_nsaid_generic").reindex(index=range(D), columns=ids)
    gen = gen.fillna("").to_numpy(dtype=object)
    cyp = people["cyp2c9_as"].to_numpy(float)
    cache: dict = {}
    nsaid_units = np.zeros((D, N))
    for d, i in zip(*np.nonzero(nsaid_on), strict=True):
        key = (gen[d, i], cyp[i])
        if key not in cache:
            mg = c["nsaid_daily_mg"].get(gen[d, i], 0.0)
            cache[key] = nsaid_units_per_day(gen[d, i], mg, cyp[i]) if mg else 0.0
        nsaid_units[d, i] = cache[key]
    gi_l_day = g["rep_vomit_episodes"] * param("vomit_loss_l") + g["rep_diarrhoea_episodes"] * param("diarrhoea_loss_l")
    phi_mult = np.where(poor > 0, param("poor_intake_mult"), 1.0)
    chronic = {"ras": people["on_ras"].to_numpy(float),
               "diuretic": people["diuretic"].map(lambda v: isinstance(v, str) and bool(v)).to_numpy(float),
               "mra": people["on_mra"].to_numpy(float), "sglt2": people["on_sglt2i"].to_numpy(float)}

    def hourly(daily: np.ndarray, a: int, b: int) -> np.ndarray:
        return np.repeat(daily, 24, axis=0)[a:b]

    # ---- device readings and labs
    z = {k: daily_pivot(ob, k, ids, D) for k in ("weight_morning", "resting_hr", "sbp_home", "steps", "sleep_hours",
                                                "skin_temp_delta")}
    lab_in = labs[(labs["reason"] != "pre_season") & labs["patient_id"].isin(ids)]
    lab_in = lab_in.drop_duplicates(["patient_id", "day"])
    lab_d = daily_pivot(lab_in, "creatinine_mg_dl", ids, D)

    # ---- static
    occ = people["occupation"].to_numpy()
    static = {
        "age": people["age"].to_numpy(float), "egfr_baseline": people["egfr_baseline"].to_numpy(float),
        "heart_failure": people["heart_failure"].to_numpy(float), "on_ras": chronic["ras"],
        "on_diuretic": chronic["diuretic"], "on_mra": chronic["mra"], "on_sglt2i": chronic["sglt2"],
        "on_metformin": people["on_metformin"].to_numpy(float),
        "loop_diuretic": people["diuretic"].isin(["furosemide", "torsemide"]).to_numpy(float),
        "beta_blocker": people["beta_blocker"].to_numpy(float), "female": people["female"].to_numpy(float),
        "uacr_mg_g": people["uacr_mg_g"].to_numpy(float), "dm": people["dm"].to_numpy(float),
        "htn": people["htn"].to_numpy(float), "ckd_g3": people["ckd_g3"].to_numpy(float),
        "cyp2c9_as": cyp, "bmi": (people["weight_kg"] / people["height_m"] ** 2).to_numpy(float),
        "outdoor_hours": people["outdoor_hours"].to_numpy(float),
        "outdoor_worker": np.isin(occ, ["vendor", "delivery", "construction_farm"]).astype(float),
        "roof_tin": (people["roof"] == "tin_asbestos").to_numpy(float),
        "cooling_none": (people["cooling"] == "none").to_numpy(float),
        "tier_code": people["tier"].map(TIER_CODE).to_numpy(float),
        "city_code": people["city"].map(CITY_CODE).to_numpy(float),
    }
    cw = city_weather_features(weather, D)
    city = people["city"].to_numpy()

    feats = {f: np.full((D, N), np.nan) for f in FULL}
    last_lab_day = np.full(N, -60.0)                     # the second pre-season lab
    last_lab_cr = labs[labs["reason"] == "pre_season"].sort_values("day").groupby("patient_id")[
        "creatinine_mg_dl"].last().reindex(ids).to_numpy(float)
    twin._start_eff({**chronic, "nsaid": nsaid_units[0]})     # chronic drugs at steady state on day 0
    for d in range(D):
        if d > 0:
            a, b = (d - 1) * 24 + 8, d * 24 + 8
            twin.predict({"sweat_l_h": sweat_h[a:b], "met": met_h[a:b], "nsaid": hourly(nsaid_units, a, b),
                          "fever_excess_c": hourly(g["rep_fever_excess_c"], a, b),
                          "gi_loss_l_h": hourly(gi_l_day, a, b) / 24, "phi_mult": hourly(phi_mult, a, b),
                          "ors_l_h": hourly(g["rep_ors_l_day"], a, b) / 24, **chronic})
        zz = np.column_stack([z["weight_morning"][d], z["resting_hr"][d], z["sbp_home"][d]])
        twin.update(zz, g["rep_fever_excess_c"][d])
        twin.update_lab(lab_d[d])
        has_lab = np.isfinite(lab_d[d])
        last_lab_day = np.where(has_lab, d, last_lab_day)
        last_lab_cr = np.where(has_lab, lab_d[d], last_lab_cr)

        # 72-hour forecast exposure (noisy, typical routine) and Monte-Carlo risk, today's reports continue as is
        fw = fc[d]
        fx = cohort_hourly_sweat(fw, people, tables=tables, start_hour=8)
        future = {"sweat_l_h": fx["sweat_l_h"], "met": fx["met"], "nsaid": nsaid_units[d],
                  "fever_excess_c": g["rep_fever_excess_c"][d], "gi_loss_l_h": gi_l_day[d] / 24,
                  "phi_mult": phi_mult[d], "ors_l_h": g["rep_ors_l_day"][d] / 24, **chronic}
        r = twin.risk_72h(future, baseline, n_draws, rng)
        f = feats
        f["mc_risk_72h"][d], f["mc_cr_peak_ratio"][d], f["mc_gfr_min_frac"][d] = r["risk"], r["cr_peak_ratio"], \
            r["gfr_min_frac"]
        f["tw_cr_ratio"][d] = twin.x[:, 2] / baseline
        f["tw_v_ecf"][d], f["tw_v_tot"][d] = twin.x[:, 1], twin.x[:, 0]
        f["tw_v_ecf_sd"][d] = np.sqrt(np.maximum(twin.P[:, 1, 1], 0))
        f["tw_cr_sd"][d] = np.sqrt(np.maximum(twin.P[:, 2, 2], 0))
        f["tw_gfr_frac"][d] = twin.gfr_frac_now()
        f["tw_theta"][d] = twin.theta
        f["fc_sweat_72h"][d] = fx["sweat_l_h"].astype(float).sum(axis=0)
        tf = np.stack([fw[c_]["temperature_2m"].to_numpy(float) for c_ in fw])            # (cities, 72)
        rh = np.stack([fw[c_]["relative_humidity_2m"].to_numpy(float) for c_ in fw])
        ci = np.array([list(fw).index(x) for x in city])
        f["fc_tmax_72h"][d] = tf.max(axis=1)[ci]
        f["fc_hi_max"][d] = heat_index_noaa(tf, rh).max(axis=1)[ci]
        f["fc_wetbulb_max"][d] = wet_bulb_stull(tf, rh).max(axis=1)[ci]
        for k in ("tmax_yesterday", "night_min_c", "hot_streak_days"):
            f[k][d] = np.array([cw[x][k].iat[d] for x in city])
        f["sweat_24h"][d] = sweat_h[max(d * 24 - 16, 0):d * 24 + 8].astype(float).sum(axis=0)
        f["rep_fever_c"][d] = g["rep_fever_excess_c"][d]
        f["rep_vomit"][d], f["rep_diarrhoea"][d] = g["rep_vomit_episodes"][d], g["rep_diarrhoea_episodes"][d]
        f["rep_gi_episodes"][d] = g["rep_vomit_episodes"][d] + g["rep_diarrhoea_episodes"][d]
        f["rep_poor_intake"][d] = poor[d]
        f["rep_ors_l"][d] = g["rep_ors_l_day"][d]
        f["nsaid_today"][d] = nsaid_units[d]
        f["nsaid_units_7d"][d] = nsaid_units[max(d - 6, 0):d + 1].sum(axis=0)
        f["triple_today"][d] = (chronic["ras"] > 0) & (chronic["diuretic"] > 0) & (nsaid_units[d] > 0)
        dry = people["weight_kg"].to_numpy(float)
        f["wt_vs_dry_kg"][d] = z["weight_morning"][d] - dry
        f["wt_delta_1d"][d] = z["weight_morning"][d] - (z["weight_morning"][d - 1] if d else np.nan)
        f["hr_delta_bpm"][d] = z["resting_hr"][d] - people["hr_base"].to_numpy(float)
        f["sbp_delta"][d] = z["sbp_home"][d] - people["sbp_base"].to_numpy(float)
        f["steps"][d], f["sleep_h"][d], f["skin_temp_delta"][d] = z["steps"][d], z["sleep_hours"][d], \
            z["skin_temp_delta"][d]
        f["band_missing"][d] = ~np.isfinite(z["resting_hr"][d])
        f["days_since_lab"][d] = d - last_lab_day
        f["last_lab_cr_ratio"][d] = last_lab_cr / baseline
        f["lab_today"][d] = has_lab
        for k, v in static.items():
            f[k][d] = v

    out = {"patient_id": np.tile(ids.to_numpy(), D), "day": np.repeat(np.arange(D), N)}
    for k, v in feats.items():
        out[k] = v.astype(np.float32).ravel()
    df = pd.DataFrame(out)
    df["season"], df["regime"], df["pool"] = season, regime, people["pool"].iat[0] if "pool" in people else ""
    tr = truth[truth["patient_id"].isin(ids)][["patient_id", "day", *LABEL_COLS]]
    return df.merge(tr, on=["patient_id", "day"], how="left", validate="one_to_one")
