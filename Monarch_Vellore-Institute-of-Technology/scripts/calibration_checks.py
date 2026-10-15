"""Cohort-level calibration targets and heat checks on the 2024 training season (Decisions v1 items 2, 10, 11).

- Heat-attributable fraction (HAF): the same patients and the same events re-run with hourly outdoor air temperature
  capped at heat_cf_cap_c (35 degC). HAF = 1 - AKI episodes (capped) / AKI episodes (actual). Overall and by subgroup.
- Heat-model sensitivity: sweat x0.7 and x1.3 -> AKI rate and HAF.
- Share of person-hours outside ISO 7933 validity, per city.
- L1 (calibration target): triple vs double therapy within antihypertensive users; pass band 1.1-2.5.
- L2 (loose sanity check): AKI episode starts vs daily maximum temperature (hospital-admission evidence ~ +0.9 %/degC
  compared with mild AKI; direction and rough size only).
Writes reports/calibration_checks.json. Episodes are counted with a 7-day gap rule (labels.episode_starts).
"""

from __future__ import annotations

import json
import sys
import time

import numpy as np
from sklearn.linear_model import PoissonRegressor

from vrikka.config import REPORTS_DIR, param
from vrikka.simulator.cohort import generate_cohort
from vrikka.simulator.ground_truth import diuretic_name
from vrikka.simulator.weather import daily_tmax
from vrikka.simulator.world import build_season, run_regime


def subgroups(people) -> dict[str, np.ndarray]:
    occ = people["occupation"].to_numpy()
    diu = people["diuretic"].map(diuretic_name).notna().to_numpy()
    return {
        "all": np.ones(len(people), bool),
        "outdoor workers": np.isin(occ, ["vendor", "delivery", "construction_farm"]),
        "home-based": occ == "home",
        "office": occ == "office",
        "age >= 60": people["age"].to_numpy() >= 60,
        "age < 60": people["age"].to_numpy() < 60,
        "on diuretic": diu,
        "not on diuretic": ~diu,
    }


def episodes(res, mask) -> int:
    return int(res["labels"]["episode_start"][:, mask].sum())


def haf_table(people, actual, capped) -> dict:
    out = {}
    for name, m in subgroups(people).items():
        a, c = episodes(actual, m), episodes(capped, m)
        out[name] = {
            "patients": int(m.sum()),
            "episodes_actual": a,
            "episodes_capped_35C": c,
            "episodes_per_100_patient_seasons": round(100 * a / max(m.sum(), 1), 1),
            "haf": round(1 - c / a, 3) if a else None,
        }
    return out


def l1(people, season, res) -> dict:
    ev, lab = season.events, res["labels"]
    both = people["on_ras"].to_numpy() & people["diuretic"].map(diuretic_name).notna().to_numpy()
    recent = np.zeros_like(ev["nsaid_on"])
    for k in range(4):
        recent[k:] |= ev["nsaid_on"][: ev["nsaid_on"].shape[0] - k]
    ok = ~lab["excluded"]
    tri = both[None, :] & ev["adherent"] & ev["nsaid_on"] & ok
    dbl = both[None, :] & ev["adherent"] & ~recent & ok
    y = lab["y"]
    rr = float(y[tri].mean() / y[dbl].mean())
    return {
        "definition": "within ACEi/ARB + diuretic users: AKI onset within 72 h on days with an NSAID (triple) vs "
        "days with no NSAID in the last 4 days (double); all NSAID courses are new (<30 days)",
        "triple_days": int(tri.sum()),
        "double_days": int(dbl.sum()),
        "risk_triple": round(float(y[tri].mean()), 4),
        "risk_double": round(float(y[dbl].mean()), 4),
        "rr": round(rr, 2),
        "pass_band": [1.1, 2.5],
        "literature": "Lapi BMJ 2013: RR 1.31 overall, 1.82 first 30 days",
        "pass": bool(1.1 <= rr <= 2.5),
    }


def l2(people, season, res) -> dict:
    tmax = daily_tmax(season.weather)
    t = tmax[people["city"].to_numpy()].to_numpy()  # (D, N)
    y = res["labels"]["episode_start"].astype(float)
    ok = ~res["labels"]["excluded"] | res["labels"]["episode_start"]
    m = PoissonRegressor(alpha=0.0, max_iter=300).fit(t[ok].reshape(-1, 1), y[ok])
    pct = 100 * (np.exp(m.coef_[0]) - 1)
    return {
        "pct_change_per_degC": round(float(pct), 2),
        "direction_ok": bool(pct > 0),
        "reference": "Brazil renal admissions ~ +0.9 %/degC (hospital admissions vs our mild KDIGO AKI)",
    }


def main() -> int:
    t0 = time.time()
    people = generate_cohort()
    base = build_season(people, 2024)
    out = {"season": 2024, "regime": "mismatched (headline)", "cap_c": param("heat_cf_cap_c")}
    runs = {}
    for label, cap, mult in (
        ("actual", None, 1.0),
        ("capped", param("heat_cf_cap_c"), 1.0),
        ("x0.7", None, param("sweat_sensitivity_low")),
        ("x0.7_capped", param("heat_cf_cap_c"), param("sweat_sensitivity_low")),
        ("x1.3", None, param("sweat_sensitivity_high")),
        ("x1.3_capped", param("heat_cf_cap_c"), param("sweat_sensitivity_high")),
    ):
        season = base if label == "actual" else build_season(people, 2024, cap, mult, events=base.events)
        runs[label] = (season, run_regime(people, season, "mismatched", with_observations=False))
        print(
            f"{label}: episodes {episodes(runs[label][1], np.ones(len(people), bool))} ({time.time() - t0:.0f} s)",
            flush=True,
        )
    out["haf"] = haf_table(people, runs["actual"][1], runs["capped"][1])
    out["sweat_sensitivity"] = {}
    for k in ("x0.7", "x1.3"):
        a, c = runs[k][1], runs[f"{k}_capped"][1]
        allm = np.ones(len(people), bool)
        out["sweat_sensitivity"][k] = {
            "episodes_per_100_patient_seasons": round(100 * episodes(a, allm) / len(people), 1),
            "haf": round(1 - episodes(c, allm) / max(episodes(a, allm), 1), 3),
        }
    matched = run_regime(people, base, "matched", with_observations=False)
    matched_cap = run_regime(people, runs["capped"][0], "matched", with_observations=False)
    out["haf_matched_regime"] = haf_table(people, matched, matched_cap)["all"]
    valid = base.exposure["valid"]
    out["outside_iso_validity_pct_of_person_hours"] = {
        c: round(100 * float((~valid[:, (people["city"] == c).to_numpy()]).mean()), 1) for c in people["city"].unique()
    }
    out["outside_iso_validity_pct_of_outdoor_hours"] = {
        c: round(
            100
            * float(
                (~valid & base.exposure["outdoors"])[:, (people["city"] == c).to_numpy()].sum()
                / max(base.exposure["outdoors"][:, (people["city"] == c).to_numpy()].sum(), 1)
            ),
            1,
        )
        for c in people["city"].unique()
    }
    out["L1"] = l1(people, base, runs["actual"][1])
    out["L2"] = l2(people, base, runs["actual"][1])
    (REPORTS_DIR / "calibration_checks.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
