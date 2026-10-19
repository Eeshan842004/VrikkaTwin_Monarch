"""Full evaluation extras (EVAL_PLAN §15.4; Amendment 1 A1.8; STATUS Part 7) -> reports/evaluation_extras.json.

    python scripts/evaluate.py                      # every section whose inputs exist
    python scripts/evaluate.py --sections tornado

Uses ONLY the frozen Part 4 model, isotonic map and thresholds (fastclock/frozen.py). Nothing is refitted or
re-thresholded on 2025 / 2026; these numbers are reported as they come out.
Sections:
  reproduction   the frozen model on the re-generated 2025 / 2026 features reproduces reports/fastclock_eval_*.json
  subgroups      M by sex, age band, diabetes, beta-blocker, city, CYP2C9 phenotype, occupation and tier (2025, 2026)
  robustness     no band, Tier 0 only, 30 % / 50 % of band days missing, noise x2, perfect vs noisy forecast (2025)
  tornado        the registry's ASSUMPTION / VERIFY ranges, one at a time, on the twin's 72-h risk for the Riya
                 persona on her red day (engine + twin sensitivity; top 10 reported)
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import numpy as np
import pandas as pd

from vrikka.config import DATA_DIR, REPORTS_DIR, SEED, load_yaml, overrides, registry
from vrikka.fastclock import frozen
from vrikka.fastclock.alerts import alert_states
from vrikka.fastclock.metrics import RankCache, alert_metrics, bootstrap_counts, ci, to_grid

FEAT = DATA_DIR / "features"
SYN = DATA_DIR / "synthetic"
REGIME = "mismatched"
MODEL = "M_hybrid_core25"
N_BOOT = 200
OUT = REPORTS_DIR / "evaluation_extras.json"


def load(path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    for c in ("y", "excluded", "onset", "episode_start"):
        df[c] = df[c].astype(bool)
    return df.sort_values(["patient_id", "day"]).reset_index(drop=True)


def events(year: int) -> pd.DataFrame:
    return pd.read_parquet(SYN / str(year) / "events_daily.parquet",
                           columns=["patient_id", "day", "fever_excess_c", "vomit_episodes", "diarrhoea_episodes",
                                    "nsaid_on"])


def score(df: pd.DataFrame, ev: pd.DataFrame, rng, model: str = MODEL, n_boot: int = N_BOOT) -> dict:
    """Day-level AUPRC (with a patient-bootstrap CI) and alert-level metrics with the frozen thresholds."""
    p = frozen.predict(df, model, REGIME)
    thr = frozen.thresholds(REGIME)[model]
    elig = ~df["excluded"].to_numpy()
    y = df["y"].to_numpy(bool)[elig]
    out = {"patients": int(df["patient_id"].nunique()), "positive_days": int(y.sum())}
    if y.sum() == 0:
        return {**out, "note": "no positive days"}
    rc = RankCache(p[elig], y)
    ap, auc = rc.ap_auc(np.ones(int(elig.sum())))
    codes, _ = pd.factorize(df.loc[elig, "patient_id"])
    boots = bootstrap_counts(codes.max() + 1, n_boot, rng)
    aps = [rc.ap_auc(b[codes][rc.order].astype(float))[0] for b in boots]
    g = df[["patient_id", "day", "excluded"]].assign(p=p)
    P, E = to_grid(g, "p", 0.0), ~to_grid(g, "excluded", 1.0).astype(bool)
    st = alert_states(P, E, thr["red_threshold"], thr["amber_threshold"])
    am = alert_metrics(df, p, st, ev, rng, n_boot)
    lead = am["lead_time"]
    return {**out, "auprc": round(ap, 4), "auprc_ci95": ci(aps), "auroc": round(auc, 4),
            "episodes": am["episodes_with_a_prediction_window"],
            "sensitivity_red": round(am["sensitivity_red"], 3), "sensitivity_red_ci95": am["sensitivity_red_ci95"],
            "sensitivity_amber_or_red": round(am["sensitivity_amber_or_red"], 3),
            "red_per_100_patient_days": round(am["red_per_100_patient_days"], 3),
            "alerts_per_aki_caught_red": round(am["alerts_per_aki_caught_red"], 1),
            "median_lead_h": lead["median_h_all_caught"], "pct_caught_ge_24h_ahead": lead["pct_caught_ge_24h_ahead"],
            "lead_by_trigger_gap": lead["by_trigger_gap"]}


# ------------------------------------------------------------------------------------------------- sections
def reproduction(rng) -> dict:
    rep = json.loads((REPORTS_DIR / f"fastclock_eval_{REGIME}.json").read_text(encoding="utf-8"))
    out = {}
    for year in (2025, 2026):
        df = load(FEAT / f"{year}_{REGIME}.parquet")
        if df is None:
            continue
        elig = ~df["excluded"].to_numpy()
        y = df["y"].to_numpy(bool)[elig]
        rows = {}
        for m in ("B4_twin_physics_risk", "B3_lightgbm_raw", MODEL, "M_full_sensitivity"):
            ap, _ = RankCache(frozen.predict(df, m, REGIME)[elig], y).ap_auc(np.ones(int(elig.sum())))
            reported = rep[f"test_{year}"][m]["day_level"]["auprc"]
            rows[m] = {"auprc_now": round(ap, 4), "auprc_reported": reported,
                       "reproduced": bool(abs(round(ap, 4) - reported) <= 0.0005)}
        out[str(year)] = {"rows": int(len(df)), "positive_days": int(y.sum()), "models": rows}
    return out


def cyp_phenotype(score_: float) -> str:
    return "normal (AS 2.0)" if score_ >= 2.0 else "intermediate (AS 1.0-1.5)" if score_ >= 1.0 else \
        "poor (AS 0-0.5)"


def subgroups(rng) -> dict:
    pub = pd.read_parquet(SYN / "patients_public.parquet").set_index("patient_id")
    groups = {
        "sex": lambda p: np.where(p["female"], "female", "male"),
        "age_band": lambda p: np.where(p["age"] < 60, "<60", np.where(p["age"] < 75, "60-74", ">=75")),
        "diabetes": lambda p: np.where(p["dm"], "diabetes", "no diabetes"),
        "beta_blocker": lambda p: np.where(p["beta_blocker"], "on beta-blocker", "not on beta-blocker"),
        "city": lambda p: p["city"].to_numpy(),
        "cyp2c9": lambda p: np.array([cyp_phenotype(s) for s in p["cyp2c9_as"]]),
        "occupation": lambda p: p["occupation"].to_numpy(),
        "tier": lambda p: p["tier"].to_numpy(),
    }
    out = {}
    for year in (2025, 2026):
        df = load(FEAT / f"{year}_{REGIME}.parquet")
        if df is None:
            continue
        ev = events(year)
        yr = {}
        for gname, fn in groups.items():
            lab = pd.Series(fn(pub), index=pub.index)
            df["_g"] = df["patient_id"].map(lab)
            yr[gname] = {str(v): score(df[df["_g"] == v].drop(columns="_g"), ev, rng)
                         for v in sorted(df["_g"].dropna().unique())}
            print(f"  subgroups {year} {gname} done", flush=True)
        out[str(year)] = yr
    return out


def robustness(rng) -> dict:
    year = 2025
    base = load(FEAT / f"{year}_{REGIME}.parquet")
    if base is None:
        return {}
    ev = events(year)
    out = {"season": year}
    for variant in ("no_band", "tier0_only", "drop30", "drop50", "noise2x", "perfect_forecast"):
        df = load(FEAT / f"robust_{variant}_{year}_{REGIME}.parquet")
        if df is None:
            continue
        ids = set(df["patient_id"])
        if "headline_noisy_forecast" not in out:          # the same patients as the variants (first test shard)
            sub = base[base["patient_id"].isin(ids)].reset_index(drop=True)
            out["patients"] = len(ids)
            out["headline_noisy_forecast"] = score(sub, ev, rng)
        out[variant] = score(df, ev, rng)
        print(f"  robustness {variant} done", flush=True)
    return out


TORNADO_SKIP_PREFIX = ("aki_", "slope_", "sglt2i_", "projection", "slow_", "whatif_", "k_beta", "r1b_", "mc_draws",
                       "kfre_", "egfr_threshold", "sweat_sensitivity", "heat_cf_cap", "paracetamol_", "phi_drink_sd",
                       "phi_drink_min", "phi_drink_max", "finerenone", "sbp_control", "stop_chronic", "baseline_egfr",
                       "creatinine_", "potassium_", "nsaid_unit", "k_tau")


def tornado(rng) -> dict:
    from vrikka.twin.replay import replay

    cfg = load_yaml("scenarios")["S1_riya"]
    day = 8
    base = replay("S1_riya", cfg).risk[day]
    rows = []
    t0 = time.time()
    for name, p in registry().items():
        lo, hi = p.range
        if p.provenance == "CITED" or lo >= hi or name.startswith(TORNADO_SKIP_PREFIX):
            continue
        vals = {}
        for edge, v in (("low", lo), ("high", hi)):
            v = int(v) if isinstance(p.value, int) and float(v).is_integer() else float(v)
            with overrides(**{name: v}):
                r = replay("S1_riya", cfg)
            vals[edge] = {"value": v, "risk": round(r.risk[day], 3),
                          "aki_onset_day": r.summary()["truth_aki_onset_day"]}
        rows.append({"parameter": name, "provenance": p.provenance, "registry_value": p.value,
                     "unit": p.unit, **vals, "swing": round(abs(vals["high"]["risk"] - vals["low"]["risk"]), 3)})
        print(f"  tornado {name}: {vals['low']['risk']} / {vals['high']['risk']} ({time.time() - t0:.0f} s)",
              flush=True)
    rows.sort(key=lambda r: -r["swing"])
    return {"output": "twin 72-h simulated kidney-injury risk for the Riya persona on her red day (S1, day 8; "
                      "demo replay on real 2024 Nagpur weather); each parameter at its registry low and high, both "
                      "the demo world and the twin use the changed value",
            "baseline_risk": round(base, 3), "parameters_screened": len(rows), "top10": rows[:10],
            "all": rows, "phi_drink_rank": next((i + 1 for i, r in enumerate(rows) if r["parameter"].startswith(
                "phi_drink")), None)}


SECTIONS = {"reproduction": reproduction, "subgroups": subgroups, "robustness": robustness, "tornado": tornado}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sections", nargs="*", default=list(SECTIONS), choices=list(SECTIONS))
    a = ap.parse_args()
    out = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    out["note"] = ("frozen Part 4 model, isotonic map and thresholds (mismatched, headline world); nothing refitted "
                   "or re-thresholded; held-out seasons scored for reporting only")
    for s in a.sections:
        t0 = time.time()
        print(f"[{s}]", flush=True)
        res = SECTIONS[s](np.random.default_rng(SEED))
        if res:
            out[s] = res
        print(f"[{s}] {time.time() - t0:.0f} s", flush=True)
        OUT.write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
