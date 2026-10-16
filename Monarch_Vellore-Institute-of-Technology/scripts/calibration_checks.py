"""Cohort-level calibration targets and heat checks on the 2024 training season (Decisions v1 items 2, 10, 11; v4 §3).

- Heat-attributable fraction (HAF): the same patients and the same events re-run with hourly outdoor air temperature
  capped at heat_cf_cap_c (35 degC). HAF = 1 - AKI episodes (capped) / AKI episodes (actual). Overall and by subgroup,
  with episode counts and patient-level bootstrap 95 % CIs (1,000 resamples, paired actual / capped), plus covariates
  and the season sweat saved by the cap per group, which explain WHY the groups differ (Decisions v4 §3).
- Heat-model sensitivity: sweat x0.7 and x1.3 -> AKI rate and HAF.
- Share of person-hours outside ISO 7933 validity, per city.
- L1 (calibration target): triple vs double therapy within antihypertensive users; pass band 1.1-2.5.
- L2 (loose sanity check): AKI episode starts vs daily maximum temperature (hospital-admission evidence ~ +0.9 %/degC
  compared with mild AKI; direction and rough size only).
Writes reports/calibration_checks.json. Episodes are counted with a 7-day gap rule (labels.episode_starts).

The 2024 training pool is processed in shards with exactly the seeds of scripts/generate_cohort.py, so the "actual"
episode count here equals the 2024 mismatched count in reports/cohort_summary.json (checked and printed).

    python scripts/calibration_checks.py                      # train pool N = 10,000
    python scripts/calibration_checks.py --n 3000 --shard 3000 \
        --out reports/engine_effect_same_patients_calibration.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.linear_model import PoissonRegressor

from vrikka.config import REPORTS_DIR, SEED, param
from vrikka.physiology.exposure import reference_tables
from vrikka.simulator.cohort import generate_cohort
from vrikka.simulator.ground_truth import diuretic_name
from vrikka.simulator.weather import daily_tmax
from vrikka.simulator.world import build_season, run_regime

SHARD_SEED_STEP = 7919          # same as scripts/generate_cohort.py
OUTDOOR = ["vendor", "delivery", "construction_farm"]


def subgroups(people) -> dict[str, np.ndarray]:
    occ = people["occupation"].to_numpy()
    diu = people["diuretic"].map(diuretic_name).notna().to_numpy()
    return {
        "all": np.ones(len(people), bool),
        "outdoor workers": np.isin(occ, OUTDOOR),
        "home-based": occ == "home",
        "office": occ == "office",
        "age >= 60": people["age"].to_numpy() >= 60,
        "age < 60": people["age"].to_numpy() < 60,
        "on diuretic": diu,
        "not on diuretic": ~diu,
    }


def occupation_groups(people) -> dict[str, np.ndarray]:
    occ = people["occupation"].to_numpy()
    return {o: occ == o for o in ("home", "office", "vendor", "delivery", "construction_farm")}


def haf_ci(a_i: np.ndarray, c_i: np.ndarray, rng, n: int = 1000) -> list[float] | None:
    """Patient-level paired bootstrap percentile interval for HAF = 1 - sum(capped) / sum(actual)."""
    if a_i.sum() == 0:
        return None
    idx = rng.integers(0, a_i.size, (n, a_i.size))
    a, c = a_i[idx].sum(1), c_i[idx].sum(1)
    ok = a > 0
    haf = 1 - c[ok] / a[ok]
    return [round(float(x), 3) for x in np.percentile(haf, [2.5, 97.5])]


def group_table(people, ep_actual, ep_capped, sweat_actual, sweat_capped, groups, rng) -> dict:
    out = {}
    for name, m in groups.items():
        a, c = ep_actual[m], ep_capped[m]
        n = int(m.sum())
        row = {
            "patients": n,
            "episodes_actual": int(a.sum()),
            "episodes_capped_35C": int(c.sum()),
            "episodes_per_100_patient_seasons": round(100 * float(a.sum()) / max(n, 1), 1),
            "haf": round(1 - float(c.sum()) / float(a.sum()), 3) if a.sum() else None,
            "haf_ci95": haf_ci(a, c, rng),
            "season_sweat_l_actual": round(float(sweat_actual[m].mean()), 1),
            "season_sweat_l_saved_by_cap": round(float((sweat_actual[m] - sweat_capped[m]).mean()), 1),
            "mean_age": round(float(people["age"][m].mean()), 1),
            "pct_on_diuretic": round(100 * float(people["diuretic"][m].map(diuretic_name).notna().mean()), 1),
            "pct_ckd_g3": round(100 * float(people["ckd_g3"][m].mean()), 1),
            "pct_diabetes": round(100 * float(people["dm"][m].mean()), 1),
            "pct_on_acei_arb": round(100 * float(people["on_ras"][m].mean()), 1),
        }
        out[name] = row
    return out


def l1_counts(people, season, res) -> np.ndarray:
    ev, lab = season.events, res["labels"]
    both = people["on_ras"].to_numpy() & people["diuretic"].map(diuretic_name).notna().to_numpy()
    recent = np.zeros_like(ev["nsaid_on"])
    for k in range(4):
        recent[k:] |= ev["nsaid_on"][: ev["nsaid_on"].shape[0] - k]
    ok = ~lab["excluded"]
    tri = both[None, :] & ev["adherent"] & ev["nsaid_on"] & ok
    dbl = both[None, :] & ev["adherent"] & ~recent & ok
    y = lab["y"]
    return np.array([tri.sum(), y[tri].sum(), dbl.sum(), y[dbl].sum()], dtype=float)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=None, help="train-pool size (default: cohort.yaml n_train_patients)")
    ap.add_argument("--shard", type=int, default=2500)
    ap.add_argument("--out", type=Path, default=REPORTS_DIR / "calibration_checks.json")
    a = ap.parse_args()
    t0 = time.time()
    pool = generate_cohort(a.n, SEED, "P")
    N = len(pool)
    cap = param("heat_cf_cap_c")
    lo, hi = param("sweat_sensitivity_low"), param("sweat_sensitivity_high")
    variants = (
        ("actual", None, 1.0), ("capped", cap, 1.0), ("x0.7", None, lo), ("x0.7_capped", cap, lo),
        ("x1.3", None, hi), ("x1.3_capped", cap, hi),
    )
    tables = reference_tables()
    ep = {v[0]: np.zeros(N, int) for v in variants}
    ep_m = {"actual": np.zeros(N, int), "capped": np.zeros(N, int)}
    sweat = {"actual": np.zeros(N), "capped": np.zeros(N)}
    l1 = np.zeros(4)
    l2_t, l2_y = [], []
    cities = list(pool["city"].unique())
    iso = {c: np.zeros(4) for c in cities}      # invalid hours, hours, invalid outdoor hours, outdoor hours
    for k, i in enumerate(range(0, N, a.shard)):
        people = pool.iloc[i : i + a.shard].reset_index(drop=True)
        sl = slice(i, i + len(people))
        seed = SEED + SHARD_SEED_STEP * k
        base = build_season(people, 2024, seed=seed, tables=tables)
        for name, c_, mult in variants:
            season = base if name == "actual" else build_season(
                people, 2024, c_, mult, seed=seed, events=base.events, tables=tables
            )
            res = run_regime(people, season, "mismatched", seed=seed, with_observations=False)
            ep[name][sl] = res["labels"]["episode_start"].sum(0)
            if name in ("actual", "capped"):
                sweat[name][sl] = season.exposure["sweat_l_h"].astype(np.float64).sum(0)
                ep_m[name][sl] = run_regime(people, season, "matched", seed=seed, with_observations=False)[
                    "labels"]["episode_start"].sum(0)
            if name == "actual":
                l1 += l1_counts(people, season, res)
                tmax = daily_tmax(season.weather)[people["city"].to_numpy()].to_numpy()
                ok = ~res["labels"]["excluded"] | res["labels"]["episode_start"]
                l2_t.append(tmax[ok].astype(np.float32))
                l2_y.append(res["labels"]["episode_start"][ok].astype(np.uint8))
                valid, outdoors = season.exposure["valid"], season.exposure["outdoors"]
                for c in cities:
                    m = (people["city"] == c).to_numpy()
                    if m.any():
                        iso[c] += [(~valid[:, m]).sum(), valid[:, m].size, ((~valid) & outdoors)[:, m].sum(),
                                   outdoors[:, m].sum()]
            del res
            if name != "actual":
                del season
        print(f"shard {k}: {len(people)} patients ({time.time() - t0:.0f} s)", flush=True)
        del base

    rng = np.random.default_rng(SEED)
    groups = subgroups(pool)
    out = {"season": 2024, "regime": "mismatched (headline)", "cap_c": cap, "n_patients": N, "shard": a.shard}
    out["haf"] = group_table(pool, ep["actual"], ep["capped"], sweat["actual"], sweat["capped"], groups, rng)
    out["haf_by_occupation"] = group_table(
        pool, ep["actual"], ep["capped"], sweat["actual"], sweat["capped"], occupation_groups(pool), rng
    )
    out["sweat_sensitivity"] = {}
    for key in ("x0.7", "x1.3"):
        A, C = ep[key].sum(), ep[f"{key}_capped"].sum()
        out["sweat_sensitivity"][key] = {
            "episodes_per_100_patient_seasons": round(100 * float(A) / N, 1),
            "haf": round(1 - float(C) / max(float(A), 1), 3),
            "haf_ci95": haf_ci(ep[key], ep[f"{key}_capped"], rng),
        }
    out["haf_matched_regime"] = {
        "episodes_actual": int(ep_m["actual"].sum()), "episodes_capped_35C": int(ep_m["capped"].sum()),
        "episodes_per_100_patient_seasons": round(100 * float(ep_m["actual"].sum()) / N, 1),
        "haf": round(1 - float(ep_m["capped"].sum()) / max(float(ep_m["actual"].sum()), 1), 3),
        "haf_ci95": haf_ci(ep_m["actual"], ep_m["capped"], rng),
    }
    out["outside_iso_validity_pct_of_person_hours"] = {c: round(100 * v[0] / v[1], 1) for c, v in iso.items()}
    out["outside_iso_validity_pct_of_outdoor_hours"] = {c: round(100 * v[2] / max(v[3], 1), 1) for c, v in iso.items()}
    tri_n, tri_y, dbl_n, dbl_y = l1
    rr = (tri_y / tri_n) / (dbl_y / dbl_n)
    out["L1"] = {
        "definition": "within ACEi/ARB + diuretic users: AKI onset within 72 h on days with an NSAID (triple) vs "
        "days with no NSAID in the last 4 days (double); all NSAID courses are new (<30 days). Single season; the "
        "pooled estimate with its bootstrap CI is in l1_pooled.json",
        "triple_days": int(tri_n), "double_days": int(dbl_n),
        "triple_events": int(tri_y), "double_events": int(dbl_y),
        "risk_triple": round(float(tri_y / tri_n), 4), "risk_double": round(float(dbl_y / dbl_n), 4),
        "rr": round(float(rr), 2), "pass_band": [1.1, 2.5],
        "literature": "Lapi BMJ 2013: RR 1.31 overall, 1.82 first 30 days",
        "pass": bool(1.1 <= rr <= 2.5),
    }
    t_all, y_all = np.concatenate(l2_t), np.concatenate(l2_y)
    m = PoissonRegressor(alpha=0.0, max_iter=300).fit(t_all.reshape(-1, 1), y_all.astype(float))
    pct = 100 * (np.exp(m.coef_[0]) - 1)
    out["L2"] = {
        "pct_change_per_degC": round(float(pct), 2),
        "direction_ok": bool(pct > 0),
        "reference": "Brazil renal admissions ~ +0.9 %/degC (hospital admissions vs our mild KDIGO AKI)",
    }
    a.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("haf", "sweat_sensitivity", "haf_matched_regime", "L1", "L2")}, indent=1))
    print(f"actual episodes (mismatched): {int(ep['actual'].sum())}  ({time.time() - t0:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
