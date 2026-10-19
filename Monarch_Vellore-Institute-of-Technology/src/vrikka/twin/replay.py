"""Day-by-day replay of a demo persona (scenarios S1-S6; master plan §11.3, §23 Time Machine).

Truth for demos = the physiology engine with the person's true sweat multiplier and drinking fraction (labelled
"demo replay"). The twin starts with population priors, reads the noisy 08:00 weight / HR (/ SBP) every morning,
and at 09:00 computes the 72-h risk on a NOISY weather forecast. Future illness, tablets and ORS are assumed to
continue as reported today ("continue as is"). KDIGO uses the daily 08:00 values and the same functions as the labels.
Alert levels here use the provisional policy thresholds (5 % / 15 %); Part 4 tunes them to the alert budget.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from vrikka.config import SEED, load_yaml, param
from vrikka.physiology.equations import aki_onsets, kdigo_daily_matrix
from vrikka.physiology.exposure import cohort_hourly_sweat, forecast_weather, load_season
from vrikka.physiology.heat import heat_index_noaa
from vrikka.physiology.pk_nsaid import activity_score, nsaid_units_from_tablets
from vrikka.physiology.renal import INPUT_DEFAULTS, Params, simulate
from vrikka.twin import measurement
from vrikka.twin.risk_mc import aki_risk_72h
from vrikka.twin.ukf_twin import KidneyTwin


def level(prob: float) -> str:
    lv = load_yaml("alert_policy")["levels"]
    return "green" if prob < lv["green"]["max_prob"] else "amber" if prob < lv["amber"]["max_prob"] else "red"


def person_frame(person: dict) -> pd.DataFrame:
    r = load_yaml("cohort")["occupation_routine"][person["occupation"]]
    return pd.DataFrame([{**person, "outdoor_start": r["outdoor_start"], "outdoor_hours": r["outdoor_hours"],
                          "works_sunday": False}])


def hot_window_start(weather_city: pd.DataFrame, days: int = 3) -> pd.Timestamp:
    w = weather_city.set_index("time")
    tmax = w["temperature_2m"].resample("D").max()
    may = tmax[tmax.index.month == 5]
    return may.rolling(days).mean().idxmax() - pd.Timedelta(days=days - 1)


@dataclass
class Replay:
    scenario: str
    dates: list
    risk: list = field(default_factory=list)
    levels: list = field(default_factory=list)
    truth_cr: list = field(default_factory=list)
    truth_stage: list = field(default_factory=list)
    twin_cr: list = field(default_factory=list)
    theta: list = field(default_factory=list)
    intra_day_rise: list = field(default_factory=list)
    heat_index_rule: list = field(default_factory=list)
    whatif: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)       # twin + 72-h inputs captured on ``capture_day`` (live what-if)
    fit: list = field(default_factory=list)            # per day: predicted vs observed morning readings, learned theta

    def summary(self) -> dict:
        onset = [i for i, s in enumerate(aki_onsets(np.array([self.truth_stage]))[0]) if s]
        red = [i for i, lv in enumerate(self.levels) if lv == "red"]
        lead = None
        if onset and red and red[0] <= onset[0]:
            lead = (onset[0] - red[0]) * 24 - 1             # first red at 09:00, onset seen at 08:00
        return {"days": len(self.dates), "max_risk": round(max(self.risk), 3),
                "levels": {lv: self.levels.count(lv) for lv in ("green", "amber", "red")},
                "truth_aki_onset_day": onset[0] if onset else None, "first_red_day": red[0] if red else None,
                "lead_time_h": lead, "max_intra_day_rise_mg_dl": round(max(self.intra_day_rise), 3),
                "heat_index_rule_days": int(sum(self.heat_index_rule)), "theta_final": round(self.theta[-1], 3)}


def _events_hourly(cfg: dict, T: int, day0_offset: int, score: float) -> dict:
    """Hourly event/drug inputs over the window. day0_offset = index of the first hot day within the window."""
    x = {k: np.zeros(T) for k in ("nsaid", "fever_excess_c", "gi_loss_l_h", "ors_l_h", "phi_mult")}
    x["phi_mult"][:] = 1.0
    day = np.arange(T) // 24 - day0_offset
    ch = cfg.get("chronic", {})
    x["ras"] = np.full(T, 1.0 if ch.get("ras") else 0.0)
    x["diuretic"] = np.full(T, 1.0 if ch.get("diuretic") else 0.0)
    x["sglt2"] = np.full(T, 1.0 if ch.get("sglt2") else 0.0)
    ev = cfg.get("events", {})
    if "nsaid" in ev:
        a, b = ev["nsaid"]["days"]
        x["nsaid"] = np.where((day >= a) & (day < b),
                              nsaid_units_from_tablets(ev["nsaid"]["brand"], ev["nsaid"]["per_day"], score), 0.0)
    if "fever" in ev:
        a, b = ev["fever"]["days"]
        on = (day >= a) & (day < b)
        x["fever_excess_c"] = np.where(on, ev["fever"]["excess_c"], 0.0)
        x["phi_mult"] = np.where(on, param("poor_intake_mult"), x["phi_mult"])
    if "gi" in ev:
        a, b = ev["gi"]["days"]
        on = (day >= a) & (day < b)
        g = ev["gi"]
        x["gi_loss_l_h"] = np.where(on, (g["vomit_per_day"] * param("vomit_loss_l")
                                         + g["diarrhoea_per_day"] * param("diarrhoea_loss_l")) / 24, 0.0)
        x["phi_mult"] = np.where(on, param("poor_intake_mult"), x["phi_mult"])
    if "ors" in ev:
        a, b = ev["ors"]["days"]
        x["ors_l_h"] = np.where((day >= a) & (day < b), ev["ors"]["l_per_day"] / 24, 0.0)
    return x


def sweat_fn_for(people: pd.DataFrame, city: str, fw: pd.DataFrame):
    """Work-hour lever helper: 72-h (sweat, met) on forecast ``fw`` with outdoor work starting at another hour."""
    def fn(start_hour: int) -> tuple[np.ndarray, np.ndarray]:
        p2 = people.assign(outdoor_start=start_hour)
        ex = cohort_hourly_sweat({city: fw}, p2, start_hour=8)
        return ex["sweat_l_h"][:, 0].astype(float), ex["met"][:, 0].astype(float)
    return fn


def replay(name: str, cfg: dict, year: int = 2024, lead_in: int = 7, after: int = 6, n_draws: int | None = None,
           seed: int = SEED, theta_true: float = 1.0, whatif_day: int | None = None,
           capture_day: int | None = None) -> Replay:
    person = cfg["person"]
    weather = load_season(year)[person["city"]]
    start = hot_window_start(weather) - pd.Timedelta(days=lead_in)
    w = weather[(weather["time"] >= start) & (weather["time"] < start + pd.Timedelta(days=lead_in + 3 + after))]
    w = w.reset_index(drop=True)
    T = len(w)
    people = person_frame(person)
    expo = cohort_hourly_sweat({person["city"]: w}, people)
    sweat, met = expo["sweat_l_h"][:, 0].astype(float), expo["met"][:, 0].astype(float)
    score = activity_score(person.get("cyp2c9", "*1/*1"))
    ev = _events_hourly(cfg, T, lead_in, score)
    diu = cfg.get("chronic", {}).get("diuretic")
    p_true = Params.from_patient(age=person["age"], female=person["female"], weight_kg=person["weight_kg"],
                                 egfr=person["egfr"], height_m=person["height_m"], diuretic=diu)
    p_true.theta_sweat = theta_true
    truth = simulate(p_true, {"sweat_l_h": sweat, "met": met, **ev})
    p_twin = Params.from_patient(age=person["age"], female=person["female"], weight_kg=person["weight_kg"],
                                 egfr=person["egfr"], height_m=person["height_m"], diuretic=diu)
    twin = KidneyTwin(p_twin, person["hr_base"], person["sbp_base"], person["beta_blocker"])
    rng = np.random.default_rng(seed)
    hours = lambda a, b: {k: v[a:b] for k, v in {"sweat_l_h": sweat, "met": met, **ev}.items()}   # noqa: E731
    n_days = T // 24 - 4
    rep = Replay(name, [str((start + pd.Timedelta(days=d + 1)).date()) for d in range(n_days)])
    hi = heat_index_noaa(w["temperature_2m"].to_numpy(), w["relative_humidity_2m"].to_numpy())
    for d in range(n_days):
        twin.predict(hours(d * 24 + 8, d * 24 + 32))
        i = (d + 1) * 24 + 7                                    # 08:00 of day d+1 (state after hour 07)
        w_obs = person["weight_kg"] - truth["v_tot"][i] + rng.normal(0, param("sigma_weight_kg"))
        hr_obs = (person["hr_base"] + (param("k_hr") * (param("k_hr_beta_blocker_mult") if person["beta_blocker"]
                                                        else 1.0)) * truth["v_ecf"][i]
                  + param("hr_fever_bpm_per_c") * ev["fever_excess_c"][i]
                  + rng.normal(0, param("sigma_hr_bpm") * (param("sigma_hr_beta_blocker_mult")
                                                           if person["beta_blocker"] else 1.0)))
        pred = measurement.hx(twin.x, person["hr_base"], person["sbp_base"], person["beta_blocker"],
                              float(ev["fever_excess_c"][i]))[0]          # what the twin expected this morning
        rep.fit.append({"weight_predicted": float(pred[0]), "weight_observed": float(w_obs),
                        "hr_predicted": float(pred[1]), "hr_observed": float(hr_obs)})
        twin.update(weight=w_obs, hr=hr_obs, fever_excess_c=float(ev["fever_excess_c"][i]))
        rep.fit[-1].update({"theta": twin.theta, "log_theta_sd": float(np.sqrt(max(twin.P[3, 3], 0.0)))})
        f_issue = i + 1
        fw = forecast_weather(w, f_issue, 72, rng)
        f_expo = cohort_hourly_sweat({person["city"]: fw}, people, start_hour=8)
        f_sweat, f_met = f_expo["sweat_l_h"][:, 0].astype(float), f_expo["met"][:, 0].astype(float)
        today = {k: float(v[i]) for k, v in ev.items()}         # "continue as is"
        future = {"sweat_l_h": f_sweat, "met": f_met, **{k: today[k] for k in today}}
        if capture_day is not None and d == capture_day:
            rep.context = {"day": d, "date": rep.dates[d], "twin": twin.snapshot(), "future": dict(future),
                           "baseline_cr": p_twin.cr_base, "seed_whatif": seed, "seed_day": seed + d,
                           "sweat_fn": sweat_fn_for(people, person["city"], fw), "score": score}
        rep.risk.append(aki_risk_72h(twin, future, p_twin.cr_base, n_draws, seed=seed + d))
        rep.levels.append(level(rep.risk[-1]))
        rep.truth_cr.append(float(truth["cr"][i]))
        rep.twin_cr.append(float(twin.x[2]))
        rep.theta.append(twin.theta)
        rep.intra_day_rise.append(float(truth["cr"][i:i + 24].max() - truth["cr"][i]))
        day_hi = hi[(d + 1) * 24:(d + 2) * 24].max()
        rep.heat_index_rule.append(bool(day_hi >= 41 and (person["age"] >= 60 or bool(diu))))
        if whatif_day is not None and d == whatif_day:
            rep.whatif = whatif_table(twin, future, p_twin.cr_base, n_draws, seed, cfg, score)
    hist = np.r_[p_twin.cr_base, rep.truth_cr]
    rep.truth_stage = kdigo_daily_matrix(hist[None, :], p_twin.cr_base)[0, 1:].tolist()
    return rep


def whatif_table(twin, future: dict, baseline: float, n_draws, seed: int, cfg: dict, score: float) -> dict:
    """Demo what-ifs in the agreed order: painkiller swap -> ORS -> drug pauses last (Decisions v1 item 1)."""
    ev = cfg.get("events", {})
    nm = nsaid_units_from_tablets(ev["nsaid"]["brand"], ev["nsaid"]["per_day"], 2.0) if "nsaid" in ev else 0.0
    pm = nsaid_units_from_tablets(ev["nsaid"]["brand"], ev["nsaid"]["per_day"], 0.0) if "nsaid" in ev else 0.0
    rows = {
        "continue as is": future,
        "1 painkiller swap: ibuprofen -> paracetamol": {**future, "nsaid": 0.0},
        "2 + ORS 1 L/day": {**future, "nsaid": 0.0, "ors_l_h": 1.0 / 24},
        "3 + pause ARB and diuretic (individualised, weak evidence, clinician decides)":
            {**future, "nsaid": 0.0, "ors_l_h": 1.0 / 24, "ras": 0.0, "diuretic": 0.0},
        "same tablets, CYP2C9 *3/*3 (poor metaboliser)": {**future, "nsaid": pm if nm else 0.0},
        "no illness, no painkiller": {**future, "nsaid": 0.0, "fever_excess_c": 0.0, "phi_mult": 1.0,
                                      "gi_loss_l_h": 0.0},
    }
    _ = INPUT_DEFAULTS, score
    return {k: round(aki_risk_72h(twin, v, baseline, n_draws, seed=seed), 3) for k, v in rows.items()}
