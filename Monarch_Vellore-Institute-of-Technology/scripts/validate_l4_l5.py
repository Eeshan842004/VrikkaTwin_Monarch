"""Loose literature checks of the physiology engine (Decisions v2 B1, B4). Not tuning targets.

L4 (heat workers; Butler-Dawson 2019, n = 517 Guatemalan cane cutters: cross-shift AKI ~50 % per month; Sorensen
2019: mean cross-shift eGFR fall 21.8 %): a young healthy heavy outdoor worker (Ravi-like: 30 y man, 70 kg, eGFR 105,
no drugs, met 3.5, 08:00-17:00 outdoors, high drinking phi 0.85) on real 2024 workdays whose approximate midday WBGT
(Australian BoM shade formula) is 30-32 degC. Report (i) share of workdays with an end-of-shift creatinine rise
>= 0.3 mg/dL or >= 1.5x pre-shift, (ii) share still raised at the next 08:00. If (i) is far outside 20-60 %, run
one-at-a-time sensitivity on tau_recover_h, ecf_frac_sweat and d50 over their registry ranges. Confounders: extreme
exertion, muscle creatinine release, point-of-care / Jaffe assay bias, a Central American population.

L5 (Belli 2018, n = 6 mountain ultramarathon runners): Cockcroft-Gault GFR fell ~25-27 % with ~3.7 % body-mass loss;
runners losing > 5 % (5.2-10.4 %) fell 27.1-44.4 %. Our engine's GFR fall at 3, 5 and 8 % body-mass loss for a healthy
young man, no drugs (sweat-driven loss). Confounders: exercise lowers renal blood flow on its own, muscle damage,
Cockcroft-Gault, n = 6.
Writes reports/literature_checks_l4_l5.json.
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace

import numpy as np
import pandas as pd

from vrikka.config import REPORTS_DIR, param, param_range
from vrikka.physiology.exposure import REF_BODY, bsa_mosteller, reference_tables
from vrikka.physiology.heat import indoor_temperature
from vrikka.physiology.renal import Params, gfr_now, simulate
from vrikka.simulator.weather import load_season

RAVI = dict(age=30, female=False, weight_kg=70.0, height_m=1.70, egfr=105.0)
PHI_HIGH = 0.85
MET_WORK = 3.5


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


def day_sweat(w: pd.DataFrame, table, bsa_ratio) -> np.ndarray:
    """Hourly sweat for previous day + work day + next day (both work days 08-17 outdoors)."""
    t, rh, sw = (w[k].to_numpy(float) for k in ("temperature_2m", "relative_humidity_2m", "shortwave_radiation"))
    hour = np.arange(len(w)) % 24
    out = (hour >= 8) & (hour < 17) & (np.arange(len(w)) < 48)
    tin = indoor_temperature(t, "concrete", "fan")
    tdb = np.where(out, t, tin)
    met = np.where(out, MET_WORK, param("met_home"))
    dtr = np.where(out, param("tr_offset_sun_c") * sw / 800, 0.0)
    s, _ = table.rate(tdb, rh, met, dtr)
    return s * bsa_ratio


def l4(params: Params, cases, table, bsa_ratio) -> dict:
    rises, residual, crit_i, crit_ii = [], [], 0, 0
    for _city, _day, w in cases:
        out = simulate(params, {"sweat_l_h": day_sweat(w, table, bsa_ratio)})["cr"]
        pre, end, nxt = out[24 + 7], out[24 + 16], out[48 + 7]  # 08:00 work day, 17:00, 08:00 next day
        rises.append(end - pre)
        residual.append(nxt - pre)
        crit_i += (end - pre >= 0.3) or (end >= 1.5 * pre)
        crit_ii += (nxt - pre >= 0.3) or (nxt >= 1.5 * pre)
    n = len(cases)
    return {
        "workdays": n,
        "share_end_of_shift_aki_pct": round(100 * crit_i / n, 1),
        "share_next_0800_still_raised_pct": round(100 * crit_ii / n, 1),
        "mean_end_of_shift_rise_mg_dl": round(float(np.mean(rises)), 3),
        "max_end_of_shift_rise_mg_dl": round(float(np.max(rises)), 3),
        "mean_next_0800_residual_mg_dl": round(float(np.mean(residual)), 3),
    }


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
    res = {
        "worker": {**RAVI, "phi_drink": PHI_HIGH, "met_work": MET_WORK, "a_tot": round(base.a_tot, 3)},
        "L4": {
            "reference": "Butler-Dawson 2019: cross-shift AKI ~51-54 % per month in heavy cane cutters",
            "target_band_pct": [20, 60],
            "default": l4(base, cases, table, bsa_ratio),
            "cities": dict(pd.Series([c for c, _, _ in cases]).value_counts()),
        },
    }
    i = res["L4"]["default"]["share_end_of_shift_aki_pct"]
    if not 20 <= i <= 60:
        sens = {}
        for name in ("tau_recover_h", "ecf_frac_sweat", "d50"):
            for v in param_range(name):
                sens[f"{name}={v}"] = l4(replace(base, **{name: v}), cases, table, bsa_ratio)
        res["L4"]["sensitivity"] = sens
    # L5: steady-state GFR fall vs body-mass loss, sweat-driven deficit
    young = Params.from_patient(**RAVI)
    l5 = {}
    for frac in (0.03, 0.05, 0.08):
        v_tot = frac * young.weight_kg
        row = {}
        for share in (param_range("ecf_frac_sweat")[0], young.ecf_frac_sweat, param_range("ecf_frac_sweat")[1]):
            row[f"ecf_share_{share}"] = round(100 * (1 - gfr_now(young, share * v_tot, 0.0, 0.0) / young.gfr_base), 1)
        l5[f"{int(frac * 100)}% body-mass loss"] = row
    res["L5"] = {
        "reference": "Belli 2018: GFR fall ~25-27 % at ~3.7 % loss; 27.1-44.4 % at 5.2-10.4 % loss",
        "engine_gfr_fall_pct": l5,
        "ceiling_note": f"healthy young kidney: maximum unprotected fall = 1 - a_tot = "
        f"{round(100 * (1 - young.a_tot), 1)} %",
    }
    (REPORTS_DIR / "literature_checks_l4_l5.json").write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    print(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
