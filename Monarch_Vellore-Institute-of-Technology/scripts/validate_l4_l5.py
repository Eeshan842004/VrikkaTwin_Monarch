"""Loose literature checks of the physiology engine and of the synthetic world (Decisions v2 B1, B4; v4 2d; v5 C2).

STATUS: REVISION-INFORMED (Amendment 2 A2.2). L4 and L5 failed in v1 (archived in reports/v1_engine/); the engine
revision (haemoconcentration C1, exertional GFR fall C2) was motivated by that failure, so the post-revision numbers are
always shown NEXT TO the v1 numbers and are never clean held-out validation. k_ex, tau_ex_h and the exertion met
thresholds were fixed in Amendment 2 before this script was re-run and are NOT fitted to L4 or L5.

L4 (heat workers; Butler-Dawson 2019, n = 517 Guatemalan cane cutters: cross-shift AKI ~50 % per month; Sorensen
2019: mean cross-shift eGFR fall 21.8 %): a young healthy heavy outdoor worker (Ravi-like: 30 y man, 70 kg, eGFR 105,
no drugs, met 3.5, 08:00-17:00 outdoors, high drinking phi 0.85) on real 2024 workdays whose approximate midday WBGT
(Australian BoM shade formula) is 30-32 degC. Report (i) share of workdays with an end-of-shift creatinine rise
>= 0.3 mg/dL or >= 1.5x pre-shift, (ii) share still raised at the next 08:00. Reported for BOTH
  (a) the twin engine (what the digital twin believes), and
  (b) the truth simulator (the synthetic world: pressure-autoregulation kidney model, hidden per-patient parameters
      drawn from the cohort generator, its own exertion constants). The truth's only muscle term is the EPISODIC
      exertional-breakdown day of heavy workers (creatinine generation x1.5-2.0, a few per cent of workdays); it is not
      switched on in this routine-workday check, so (b) shows exertion + haemoconcentration only.
Also reported: the mean cross-shift eGFR fall implied by the creatinine rise (CKD-EPI 2021), which is the measure
Sorensen 2019 reported (-21.8 %, SD 13.6 %, WBGT ~31 degC, n = 105).
Confounders: extreme exertion, muscle creatinine release, point-of-care / Jaffe assay bias, a Central American
population.

L5 (Belli 2018, n = 6 mountain ultramarathon runners): Cockcroft-Gault GFR fell ~25-27 % with ~3.7 % body-mass loss;
runners losing > 5 % (5.2-10.4 %) fell 27.1-44.4 %. GFR fall at 3, 5 and 8 % body-mass loss for a healthy young man,
no drugs, in the engine and in the truth simulator, (1) from dehydration alone (comparable with v1) and (2) with
sustained full exertion on top (an ultramarathon is exercise: the exertion term is at its maximum). Confounders:
exercise lowers renal blood flow on its own, muscle damage, Cockcroft-Gault, n = 6. Not a tuning target.

Writes reports/literature_checks_l4_l5.json.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace

import numpy as np
import pandas as pd

from vrikka.config import REPORTS_DIR, param, param_range
from vrikka.physiology.equations import creatinine_from_egfr, egfr_ckd_epi_2021
from vrikka.physiology.exposure import REF_BODY, bsa_mosteller, reference_tables
from vrikka.physiology.heat import indoor_temperature
from vrikka.physiology.renal import Params, gfr_now, simulate
from vrikka.simulator.cohort import generate_cohort
from vrikka.simulator.ground_truth import pressure_gfr_fraction, simulate_truth
from vrikka.simulator.weather import load_season

RAVI = dict(age=30, female=False, weight_kg=70.0, height_m=1.70, egfr=105.0)
PHI_HIGH = 0.85
MET_WORK = 3.5
REC_HOURS = (24 + 7, 24 + 16, 48 + 7)  # 08:00 work day (pre-shift), 17:00 (end of shift), next 08:00


def wbgt_bom(t, rh):
    e = rh / 100 * 6.105 * np.exp(17.27 * t / (237.7 + t))
    return 0.567 * t + 0.393 * e + 3.94


def hot_workdays(year=2024) -> list[tuple[str, pd.Timestamp]]:
    days = []
    for city, w in load_season(year).items():
        w = w.set_index("time")
        wb = wbgt_bom(w["temperature_2m"], w["relative_humidity_2m"]).resample("D").max()
        sel = wb[(wb >= 30) & (wb <= 32)].index
        days += [
            (city, d) for d in sel if d - pd.Timedelta(days=1) >= w.index[0] and d + pd.Timedelta(days=2) <= w.index[-1]
        ]
    return days


def day_inputs(w: pd.DataFrame, table, bsa_ratio) -> tuple[np.ndarray, np.ndarray]:
    """Hourly sweat (L/h) and met for previous day + work day + next day (both work days 08-17 outdoors)."""
    t, rh, sw = (w[k].to_numpy(float) for k in ("temperature_2m", "relative_humidity_2m", "shortwave_radiation"))
    hour = np.arange(len(w)) % 24
    out = (hour >= 8) & (hour < 17) & (np.arange(len(w)) < 48)
    tin = indoor_temperature(t, "concrete", "fan")
    tdb = np.where(out, t, tin)
    met = np.where(out, MET_WORK, param("met_home"))
    dtr = np.where(out, param("tr_offset_sun_c") * sw / 800, 0.0)
    s, _ = table.rate(tdb, rh, met, dtr)
    return s * bsa_ratio, met


def summarise(pre, end, nxt) -> dict:
    pre, end, nxt = (np.asarray(a, float) for a in (pre, end, nxt))
    crit_i = ((end - pre) >= 0.3) | (end >= 1.5 * pre)
    crit_ii = ((nxt - pre) >= 0.3) | (nxt >= 1.5 * pre)
    egfr_fall = 100 * (
        1 - egfr_ckd_epi_2021(end, RAVI["age"], RAVI["female"]) / egfr_ckd_epi_2021(pre, RAVI["age"], RAVI["female"])
    )
    return {
        "workdays": int(pre.size),
        "share_end_of_shift_aki_pct": round(100 * float(crit_i.mean()), 1),
        "share_next_0800_still_raised_pct": round(100 * float(crit_ii.mean()), 1),
        "mean_end_of_shift_rise_mg_dl": round(float(np.mean(end - pre)), 3),
        "p90_end_of_shift_rise_mg_dl": round(float(np.percentile(end - pre, 90)), 3),
        "max_end_of_shift_rise_mg_dl": round(float(np.max(end - pre)), 3),
        "mean_cross_shift_egfr_fall_pct": round(float(np.mean(egfr_fall)), 1),
        "mean_next_0800_residual_mg_dl": round(float(np.mean(nxt - pre)), 3),
    }


def l4_engine(params: Params, cases, table, bsa_ratio) -> dict:
    pre, end, nxt = [], [], []
    for _city, _day, w in cases:
        sweat, met = day_inputs(w, table, bsa_ratio)
        out = simulate(params, {"sweat_l_h": sweat, "met": met})["cr"]
        pre.append(out[REC_HOURS[0]])
        end.append(out[REC_HOURS[1]])
        nxt.append(out[REC_HOURS[2]])
    return summarise(pre, end, nxt)


def ravi_people(n: int, seed: int) -> pd.DataFrame:
    """Ravi-like young healthy workers whose HIDDEN truth parameters come from the cohort generator's distributions."""
    p = generate_cohort(n, seed=seed, id_prefix="L")
    rng = np.random.default_rng(seed + 7)
    p["age"], p["female"], p["weight_kg"], p["height_m"] = 30, False, 70.0, 1.70
    p["egfr_baseline"] = 105.0
    p["cr_baseline"] = round(creatinine_from_egfr(105.0, 30, False), 3)
    for c in ("on_ras", "on_mra", "on_sglt2i"):
        p[c] = False
    p["diuretic"] = None
    p["water_access_at_work"] = True
    p["true_phi_drink"] = PHI_HIGH
    p["sbp_base"], p["dbp_base"] = rng.normal(121, 10, n).round(0), rng.normal(78, 7, n).round(0)
    p["true_lla"] = (75 + 0.25 * (30 - 50) + rng.normal(0, 4, n)).round(1)  # normotensive, no CKD
    return p


def quiet_events(n: int, days: int = 3) -> dict:
    z = np.zeros((days, n))
    return {
        "fever_excess_c": z,
        "vomit_episodes": z,
        "diarrhoea_episodes": z,
        "poor_intake": np.zeros((days, n), bool),
        "nsaid_units": z,
        "ors_l_day": z,
        "adherent": np.ones((days, n), bool),
        "sepsis_like": np.zeros((days, n), bool),
        "rhabdo": np.zeros((days, n), bool),
        "cotrimoxazole": np.zeros((days, n), bool),
    }


def l4_truth(cases, table, bsa_ratio, seed: int) -> dict:
    n = len(cases)
    people = ravi_people(n, seed)
    per_case = [day_inputs(w, table, bsa_ratio) for _, _, w in cases]
    sweat, met = (np.stack(a, axis=1) for a in zip(*per_case, strict=True))
    res = simulate_truth(
        people, sweat, quiet_events(n), "mismatched", seed=seed, met=met, record_hours=REC_HOURS
    )
    pre, end, nxt = res["cr_at"]
    return summarise(pre, end, nxt)


def l5(young: Params, seed: int = 123) -> dict:
    fracs = (0.03, 0.05, 0.08)
    lo, hi = param_range("ecf_frac_sweat")
    eng, eng_ex = {}, {}
    for frac in fracs:
        v_tot = frac * young.weight_kg
        row, row_ex = {}, {}
        for share in (lo, young.ecf_frac_sweat, hi):
            fall = 1 - gfr_now(young, share * v_tot, 0.0, 0.0) / young.gfr_base
            row[f"ecf_share_{share}"] = round(100 * fall, 1)
            row_ex[f"ecf_share_{share}"] = round(100 * (1 - (1 - fall) * (1 - young.k_ex)), 1)
        eng[f"{int(frac * 100)}% body-mass loss"], eng_ex[f"{int(frac * 100)}% body-mass loss"] = row, row_ex
    people = ravi_people(2000, seed)
    map_base = ((people["sbp_base"] + 2 * people["dbp_base"]) / 3).to_numpy(float)
    truth, truth_ex = {}, {}
    for frac in fracs:
        v_ecf = people["true_ecf_frac_sweat"].to_numpy(float) * frac * young.weight_kg
        f = pressure_gfr_fraction(
            v_ecf, map_base, people["true_k_map"].to_numpy(float), people["true_lla"].to_numpy(float)
        )
        for store, fall in ((truth, 1 - f), (truth_ex, 1 - f * (1 - people["true_k_ex"].to_numpy(float)))):
            q = np.percentile(100 * fall, [10, 50, 90])
            store[f"{int(frac * 100)}% body-mass loss"] = {"p10": round(q[0], 1), "median": round(q[1], 1),
                                                           "p90": round(q[2], 1)}
    return {"twin_engine_dehydration_only": eng, "twin_engine_with_sustained_exertion": eng_ex,
            "truth_simulator_dehydration_only": truth, "truth_simulator_with_sustained_exertion": truth_ex}


def main() -> int:
    base = Params.from_patient(**RAVI)
    base.phi_drink = PHI_HIGH
    table = reference_tables()[False]
    bsa_ratio = bsa_mosteller(RAVI["weight_kg"], RAVI["height_m"]) / bsa_mosteller(*REF_BODY[False][:2])
    seasons = {c: w.set_index("time") for c, w in load_season(2024).items()}
    cases = []
    for city, d in hot_workdays():
        w = seasons[city].loc[d - pd.Timedelta(days=1) : d + pd.Timedelta(days=1, hours=23)].reset_index()
        cases.append((city, d, w))
    v1 = json.loads((REPORTS_DIR / "v1_engine" / "literature_checks_l4_l5.json").read_text(encoding="utf-8"))
    res = {
        "status": "revision-informed (Amendment 2 A2.2): shown next to the v1 failure, not clean validation",
        "worker": {**RAVI, "phi_drink": PHI_HIGH, "met_work": MET_WORK, "a_tot": round(base.a_tot, 3),
                   "k_ex": base.k_ex, "tau_ex_h": base.tau_ex_h,
                   "exertion_fraction_at_met_work": round(float(min(max((MET_WORK - base.ex_met_threshold)
                                                                         / base.ex_met_span, 0), 1)), 3)},
        "L4": {
            "reference": "Butler-Dawson 2019: cross-shift AKI ~51-54 % per month in heavy cane cutters; "
            "Sorensen 2019: mean cross-shift eGFR fall 21.8 % (SD 13.6 %)",
            "target_band_pct": [20, 60],
            "v1_engine_before_revision": v1["L4"]["default"],
            "twin_engine": l4_engine(base, cases, table, bsa_ratio),
            "truth_simulator": l4_truth(cases, table, bsa_ratio, seed=2024),
            "cities": dict(pd.Series([c for c, _, _ in cases]).value_counts()),
        },
    }
    i = res["L4"]["twin_engine"]["share_end_of_shift_aki_pct"]
    if not 20 <= i <= 60:
        sens = {}
        for name in ("tau_recover_h", "ecf_frac_sweat", "d50", "k_ex", "tau_ex_h", "vd_floor_frac"):
            for v in param_range(name):
                sens[f"{name}={v}"] = l4_engine(replace(base, **{name: v}), cases, table, bsa_ratio)
        res["L4"]["twin_engine_sensitivity"] = sens
    young = Params.from_patient(**RAVI)
    res["L5"] = {
        "reference": "Belli 2018: GFR fall ~25-27 % at ~3.7 % loss; 27.1-44.4 % at 5.2-10.4 % loss",
        "v1_engine_gfr_fall_pct": v1["L5"]["engine_gfr_fall_pct"],
        **l5(young),
        "ceiling_note": f"healthy young kidney, dehydration only: maximum unprotected fall = 1 - a_tot = "
        f"{round(100 * (1 - young.a_tot), 1)} %",
        "caveats": "an ultramarathon adds exercise (lower renal blood flow on its own), muscle damage and a "
        "Cockcroft-Gault GFR; n = 6. Chapman 2020: GFR fell ~12 % only in markedly dehydrated subjects, which matches "
        "the dehydration-only rows. The 'with sustained exertion' rows use the pre-registered k_ex (not fitted).",
    }
    (REPORTS_DIR / "literature_checks_l4_l5.json").write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    print(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
