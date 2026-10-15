"""Gate G2: reproduce the §9.1 scenario ordering with the real engine, plus an engine-level heat check.

Patient: Kamala-like (68 y woman, 62 kg, 1.55 m, baseline eGFR 58), all other values from the registry
(phi_drink 0.60 because age >= 60). Weather: the 3 hottest consecutive days of the real 2024 Nagpur season.
Day plan: 7 quiet burn-in days indoors (28 degC) so chronic drugs reach steady state, 3 hot days with 9 h outdoors
(08:00-17:00, light outdoor work, met_vendor), then 2 quiet recovery days so the creatinine peak is caught.
Drugs: telmisartan (ARB) + chlorthalidone are chronic; Combiflam 3/day (ibuprofen 1,200 mg) on the 3 hot days;
fever 38.5 degC (1.5 degC above 37) on hot days 2-3.

Heat check (Decisions v1 item 2): identical run with outdoor air temperature capped at heat_cf_cap_c (35 degC).
KDIGO uses one creatinine per day at 08:00 and the §9.3 baseline rule, exactly like the labels will.

Writes reports/physiology_scenarios.json. Every number in the G2 report comes from this file.
"""
from __future__ import annotations

import json
import sys
import time

import numpy as np
import pandas as pd

from vrikka.config import DATA_DIR, REPORTS_DIR, param
from vrikka.physiology.batch import simulate_vec, stack_params
from vrikka.physiology.equations import baseline_creatinine, daily_samples, egfr_ckd_epi_2021, kdigo_daily_stages
from vrikka.physiology.heat import indoor_temperature, load_sweat_table, mean_radiant_offset, met_for_occupation
from vrikka.physiology.pk_nsaid import activity_score, nsaid_units_from_tablets
from vrikka.physiology.renal import Params, simulate

PERSON = dict(age=68, female=True, weight_kg=62.0, egfr=58.0, height_m=1.55)
BURN_IN, HOT, RECOVER = 7, 3, 2
QUIET = dict(tdb=28.0, rh=50.0)
OUTDOOR_HOURS = range(8, 17)        # 9 hours outdoors
FEVER_EXCESS_C = 1.5               # 38.5 degC
FEVER_DAYS = (1, 2)                # hot days 2 and 3 (0-based)


def hottest_window(city="Nagpur", year=2024, days=HOT) -> pd.DataFrame:
    w = pd.read_parquet(DATA_DIR / "weather" / str(year) / f"{city}.parquet")
    tmax = w.set_index("time")["temperature_2m"].resample("D").max()
    start = tmax.rolling(days).mean().idxmax() - pd.Timedelta(days=days - 1)
    return w[(w["time"] >= start) & (w["time"] < start + pd.Timedelta(days=days))].reset_index(drop=True)


def exposure(hot: pd.DataFrame, cap_c: float | None, table) -> dict:
    """Hourly sweat (L/h) and ISO-validity flags for burn-in + hot + recovery days."""
    tdb_out = hot["temperature_2m"].to_numpy()
    if cap_c is not None:
        tdb_out = np.minimum(tdb_out, cap_c)
    hour = np.arange(len(hot)) % 24
    outdoors = np.isin(hour, list(OUTDOOR_HOURS))
    tdb_in = indoor_temperature(tdb_out, roof="concrete", cooling="none")
    tdb = np.where(outdoors, tdb_out, tdb_in)
    met = np.where(outdoors, met_for_occupation("vendor"), met_for_occupation("home"))
    dtr = mean_radiant_offset(hot["shortwave_radiation"].to_numpy(), outdoors)
    sweat_hot, ok_hot = table.rate(tdb, hot["relative_humidity_2m"].to_numpy(), met, dtr)
    sweat_quiet, ok_quiet = table.rate(QUIET["tdb"], QUIET["rh"], met_for_occupation("home"), 0.0)
    q = np.full(24 * BURN_IN, float(sweat_quiet))
    r = np.full(24 * RECOVER, float(sweat_quiet))
    return {"sweat": np.r_[q, sweat_hot, r], "valid_hot": ok_hot, "tdb_hot": tdb,
            "outdoor_hours_outside_iso": float((~ok_hot[outdoors]).mean())}


def drug_inputs(T: int, ras_diu: bool, nsaid_units: float, fever: bool) -> dict:
    day = np.arange(T) // 24
    on_hot = (day >= BURN_IN) & (day < BURN_IN + HOT)
    x = {"ras": np.full(T, float(ras_diu)), "diuretic": np.full(T, float(ras_diu)),
         "nsaid": np.where(on_hot, nsaid_units, 0.0), "fever_excess_c": np.zeros(T)}
    if fever:
        x["fever_excess_c"] = np.where(np.isin(day - BURN_IN, FEVER_DAYS), FEVER_EXCESS_C, 0.0)
    return x


def run(p: Params, sweat: np.ndarray, drugs: dict) -> dict:
    T = len(sweat)
    out = simulate(p, {"sweat_l_h": sweat, **drugs})
    t = np.arange(T, dtype=float) + 1.0           # state after hour h is at time h+1 (hours since midnight)
    td, cd = daily_samples(t, out["cr"])
    burn_days = [(float(d) / 24, float(c)) for d, c in zip(td, cd, strict=True) if d < BURN_IN * 24]
    base, src = baseline_creatinine(burn_days, BURN_IN, p.age, p.female)
    _, stages = kdigo_daily_stages(t, out["cr"], baseline=base)
    ref = out["cr"][BURN_IN * 24 - 1]
    window = slice(BURN_IN * 24, T)
    return {
        "peak_v_tot_l": round(float(out["v_tot"][window].max()), 3),
        "peak_v_ecf_l": round(float(out["v_ecf"][window].max()), 3),
        "peak_delta_cr_hourly_mg_dl": round(float(out["cr"][window].max() - ref), 3),
        "peak_delta_cr_0800_mg_dl": round(float(cd[td >= BURN_IN * 24].max() - base), 3),
        "min_gfr_pct": round(float(100 * out["gfr"][window].min() / p.gfr_base), 1),
        "kdigo_max_stage_0800": int(stages.max()),
        "aki": bool(stages.max() > 0),
        "baseline_cr_mg_dl": round(base, 3), "baseline_rule": src,
    }


def scenario_table(table, hot, phi_override: float | None = None) -> dict:
    with_drugs = Params.from_patient(**PERSON, diuretic="chlorthalidone")
    no_drugs = Params.from_patient(**PERSON)
    if phi_override is not None:
        with_drugs.phi_drink = no_drugs.phi_drink = phi_override
    nm = nsaid_units_from_tablets("combiflam", 3, activity_score("*1/*1"))
    pm = nsaid_units_from_tablets("combiflam", 3, activity_score("*3/*3"))
    rows = [
        ("1 no drugs", no_drugs, False, 0.0, False),
        ("2 NSAID only (Combiflam x3)", no_drugs, False, nm, False),
        ("3 ARB + diuretic", with_drugs, True, 0.0, False),
        ("4 triple whammy", with_drugs, True, nm, False),
        ("5 ARB + diuretic + fever", with_drugs, True, 0.0, True),
        ("6 triple whammy + fever", with_drugs, True, nm, True),
        ("7 triple + fever, CYP2C9 poor metaboliser (*3/*3)", with_drugs, True, pm, True),
    ]
    out = {"actual": {}, "capped_35C": {}}
    for cap_name, cap in (("actual", None), ("capped_35C", param("heat_cf_cap_c"))):
        ex = exposure(hot, cap, table)
        for name, p, rd, nsaid, fever in rows:
            out[cap_name][name] = run(p, ex["sweat"], drug_inputs(len(ex["sweat"]), rd, nsaid, fever))
        out[cap_name]["_hot_day_sweat_l"] = round(float(ex["sweat"][BURN_IN * 24:(BURN_IN + HOT) * 24].sum()), 2)
        out[cap_name]["_outdoor_hours_outside_iso_validity"] = round(ex["outdoor_hours_outside_iso"], 3)
        out[cap_name]["_max_air_temp_c"] = round(float(ex["tdb_hot"].max()), 1)
    haf = {}
    for name, *_ in rows:
        a = out["actual"][name]["peak_delta_cr_hourly_mg_dl"]
        c = out["capped_35C"][name]["peak_delta_cr_hourly_mg_dl"]
        haf[name] = {"delta_cr_actual": a, "delta_cr_capped": c,
                     "heat_share_of_rise": round(1 - c / a, 2) if a > 1e-3 else None,
                     "aki_actual": out["actual"][name]["aki"], "aki_capped": out["capped_35C"][name]["aki"]}
    out["heat_attribution"] = haf
    return out


def benchmark() -> dict:
    """Vectorised engine speed: 33,000 trajectories x 2,928 hourly steps (a 122-day season)."""
    rng = np.random.default_rng(42)
    base = Params.from_patient(**PERSON, diuretic="chlorthalidone")
    P = stack_params([base])
    N, T = 33_000, 2_928
    P = {k: np.repeat(v, N) for k, v in P.items()}
    P["theta_sweat"] = rng.uniform(0.7, 1.4, N)
    sweat = (np.arange(T) % 24 >= 8) & (np.arange(T) % 24 < 17)
    t0 = time.time()
    simulate_vec(P, {"sweat_l_h": sweat[:, None] * 0.4, "ras": np.ones(T), "diuretic": np.ones(T)}, record=())
    return {"trajectories": N, "hourly_steps": T, "seconds": round(time.time() - t0, 1)}


def main() -> int:
    hot = hottest_window()
    p0 = Params.from_patient(**PERSON, diuretic="chlorthalidone")
    table = load_sweat_table(PERSON["weight_kg"], PERSON["height_m"], param("clo_light_cotton"))
    res = {
        "patient": {**PERSON, "baseline_cr_mg_dl": round(p0.cr_base, 3),
                    "egfr_check": round(egfr_ckd_epi_2021(p0.cr_base, 68, True), 1), "a_tot": round(p0.a_tot, 3),
                    "phi_drink": p0.phi_drink, "gfr_base_abs_ml_min": round(p0.gfr_base, 1)},
        "weather": {"city": "Nagpur", "days": [str(hot['time'].iloc[0].date()), str(hot['time'].iloc[-1].date())],
                    "tmax_c": round(float(hot["temperature_2m"].max()), 1),
                    "rh_mean_pct": round(float(hot["relative_humidity_2m"].mean()), 1)},
        "design": {"burn_in_days": BURN_IN, "hot_days": HOT, "recovery_days": RECOVER,
                   "outdoor_hours": f"{OUTDOOR_HOURS.start:02d}:00-{OUTDOOR_HOURS.stop:02d}:00",
                   "outdoor_met": met_for_occupation("vendor"), "fever": "38.5 degC on hot days 2-3",
                   "nsaid": "Combiflam 3/day = ibuprofen 1,200 mg/day on the hot days",
                   "kdigo": "one creatinine per day at 08:00, §9.3 baseline rule"},
        "registry_defaults": scenario_table(table, hot),
        "plan_comparable_phi_0_75": scenario_table(table, hot, phi_override=0.75),
        "benchmark": benchmark(),
    }
    dest = REPORTS_DIR / "physiology_scenarios.json"
    dest.write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("patient", "weather", "benchmark")}, indent=1))
    for regime in ("registry_defaults", "plan_comparable_phi_0_75"):
        print(f"\n== {regime}")
        for cap in ("actual", "capped_35C"):
            print(f"  [{cap}] hot-day sweat {res[regime][cap]['_hot_day_sweat_l']} L, "
                  f"max air {res[regime][cap]['_max_air_temp_c']} C, "
                  f"outdoor hours outside ISO {res[regime][cap]['_outdoor_hours_outside_iso_validity']}")
            for name, r in res[regime][cap].items():
                if not name.startswith("_"):
                    print(f"    {name:52s} v_tot {r['peak_v_tot_l']:.2f}  v_ecf {r['peak_v_ecf_l']:.2f}  "
                          f"dCr(h) {r['peak_delta_cr_hourly_mg_dl']:+.3f}  dCr(08) {r['peak_delta_cr_0800_mg_dl']:+.3f}"
                          f"  GFR {r['min_gfr_pct']}%  KDIGO {r['kdigo_max_stage_0800']}")
    print(f"\nwrote {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
