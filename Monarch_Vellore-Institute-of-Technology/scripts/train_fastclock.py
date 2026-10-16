"""Train the fast clock, tune the alert thresholds, evaluate and write the G3 decision (Part 4; Amendment 2 A2.5-A2.6).

    python scripts/train_fastclock.py                     # mismatched (headline) and matched, if their features exist

Order, fixed in advance (Amendment 2):
1. Fit B0, B3, M and M_full on the 2024 TRAIN split, early stopping on the 2024 EARLY-STOP split; isotonic calibration
   of every model on the 2024 CALIBRATION split; alert thresholds tuned on the same calibration split (red <= 0.5 and
   amber + red <= 3 notifications per 100 patient-days).
2. Freeze. Evaluate on the 2024 INTERNAL-TEST patients (used for the G3 decision) and then, once, on the 2025 and 2026
   test seasons (separate test patients). Nothing is refitted after step 1.
Writes models/ (LightGBM text models, isotonic maps, thresholds), reports/fastclock_eval_<regime>.json and
reports/g3_decision.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import numpy as np
import pandas as pd

from vrikka.config import DATA_DIR, MODELS_DIR, REPORTS_DIR, SEED
from vrikka.fastclock.alerts import alert_states, tune_thresholds
from vrikka.fastclock.explain import top_reasons
from vrikka.fastclock.features import CORE, FULL, LABEL_COLS
from vrikka.fastclock.metrics import alert_metrics, bootstrap_counts, ci, day_metrics, to_grid
from vrikka.fastclock.train import save, train_all

FEAT = DATA_DIR / "features"
SYN = DATA_DIR / "synthetic"
BASELINES_G3 = ("B0_last_lab_logistic", "B1_heat_index_rule", "B2_triple_heat_egfr_points")
N_BOOT = 1000


def load(year: int, regime: str) -> pd.DataFrame | None:
    f = FEAT / f"{year}_{regime}.parquet"
    if not f.exists():
        return None
    df = pd.read_parquet(f)
    for c in ("y", "excluded", "onset", "episode_start"):
        df[c] = df[c].astype(bool)
    return df.sort_values(["patient_id", "day"]).reset_index(drop=True)


def grid(df: pd.DataFrame, p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    g = df[["patient_id", "day", "excluded"]].assign(p=p)
    return to_grid(g, "p", 0.0), ~to_grid(g, "excluded", 1.0).astype(bool)


def evaluate_set(name: str, df: pd.DataFrame, models: dict, thr: dict, events, rng) -> dict:
    elig = df[~df["excluded"]]
    codes, _ = pd.factorize(elig["patient_id"])
    boots = bootstrap_counts(codes.max() + 1, N_BOOT, rng)
    out, boot_ap = {}, {}
    for mname, m in models.items():
        p_all = m.predict(df)
        dm = day_metrics(elig, p_all[~df["excluded"].to_numpy()], boots)
        boot_ap[mname] = dm.pop("_boot_ap")
        P, E = grid(df, p_all)
        st = alert_states(P, E, thr[mname]["red_threshold"], thr[mname]["amber_threshold"])
        am = alert_metrics(df, p_all, st, events, rng, N_BOOT)
        out[mname] = {"day_level": dm, "alerts": am}
        print(f"  {name:14s} {mname:28s} AUPRC {dm['auprc']:.4f} {dm['auprc_ci95']}  AUROC {dm['auroc']:.3f}  "
              f"red/100pd {am['red_per_100_patient_days']:.2f}  sens_red {am['sensitivity_red']:.2f}  "
              f"alerts/caught {am['alerts_per_aki_caught_red']:.1f}", flush=True)
    m_ap = boot_ap["M_hybrid_core25"]
    out["_paired_auprc_difference_M_minus"] = {b: {"point": round(out["M_hybrid_core25"]["day_level"]["auprc"]
                                                                  - out[b]["day_level"]["auprc"], 4),
                                                   "ci95": ci(m_ap - boot_ap[b])}
                                               for b in models if b != "M_hybrid_core25"}
    return out


def subgroup_age75(df: pd.DataFrame, models: dict, thr: dict, events, rng) -> dict:
    pp = pd.read_parquet(SYN / "patients_public.parquet", columns=["patient_id", "age"])
    ids = set(pp.loc[pp["age"] >= 75, "patient_id"])
    sub = df[df["patient_id"].isin(ids)]
    if sub.empty or sub.loc[~sub["excluded"], "y"].sum() == 0:
        return {"patients": int(sub["patient_id"].nunique()), "note": "no positive days"}
    m = models["M_hybrid_core25"]
    elig = sub[~sub["excluded"]]
    codes, _ = pd.factorize(elig["patient_id"])
    p_all = m.predict(sub)
    dm = day_metrics(elig, p_all[~sub["excluded"].to_numpy()], bootstrap_counts(codes.max() + 1, 300, rng))
    dm.pop("_boot_ap")
    P, E = grid(sub, p_all)
    am = alert_metrics(sub, p_all, alert_states(P, E, thr["M_hybrid_core25"]["red_threshold"],
                                                thr["M_hybrid_core25"]["amber_threshold"]), events, rng, 300)
    return {"patients": int(sub["patient_id"].nunique()), "auprc": dm["auprc"], "auprc_ci95": dm["auprc_ci95"],
            "auroc": dm["auroc"], "sensitivity_red": am["sensitivity_red"], "episodes": am[
                "episodes_with_a_prediction_window"],
            "note": "low muscle mass can blunt creatinine rises in older people, so creatinine-defined AKI may be "
                    "under-detected (Decisions v4 5d)"}


def run(regime: str, rng) -> dict | None:
    d24 = load(2024, regime)
    if d24 is None:
        print(f"no 2024 {regime} features; skipped")
        return None
    t0 = time.time()
    train = d24[(d24["split"] == "train") & ~d24["excluded"]]
    episodes_train = int(train.groupby("patient_id")["y"].apply(
        lambda s: (s.astype(int).diff().fillna(s.iloc[0]) > 0).sum()).sum())
    epf = {"core_features": len(CORE), "full_features": len(FULL), "train_positive_days": int(train["y"].sum()),
           "train_positive_runs_approx_episodes": episodes_train,
           "positive_days_per_core_feature": round(train["y"].sum() / len(CORE), 1),
           "episodes_per_core_feature": round(episodes_train / len(CORE), 1),
           "positive_days_per_full_feature": round(train["y"].sum() / len(FULL), 1)}
    fit = d24[d24["split"].isin(["train", "early_stop", "calibration"]) & ~d24["excluded"]]
    models, boosters = train_all(fit)
    print(f"{regime}: trained in {time.time() - t0:.0f} s; M rounds {boosters['M'].best_iteration}", flush=True)
    cal = d24[d24["split"] == "calibration"]
    thr = {}
    for name, m in models.items():
        P, E = grid(cal, m.predict(cal))
        thr[name] = tune_thresholds(P, E)
    save(models, boosters, thr, MODELS_DIR, regime)
    ev = {}
    for year in (2025, 2026):
        e = SYN / str(year) / "events_daily.parquet"
        ev[year] = pd.read_parquet(e, columns=["patient_id", "day", "fever_excess_c", "vomit_episodes",
                                                "diarrhoea_episodes", "nsaid_on"])
    ev24 = pd.read_parquet(SYN / "2024" / "events_daily.parquet", columns=["patient_id", "day", "fever_excess_c",
                                                                            "vomit_episodes", "diarrhoea_episodes",
                                                                            "nsaid_on"])
    res = {"regime": regime, "events_per_feature": epf, "thresholds": thr,
           "lgb_best_iterations": {k: int(b.best_iteration) for k, b in boosters.items()}}
    res["internal_test_2024"] = evaluate_set("2024 internal", d24[d24["split"] == "internal_test"], models, thr,
                                             ev24, rng)
    del d24
    for year in (2025, 2026):
        d = load(year, regime)
        if d is None:
            continue
        res[f"test_{year}"] = evaluate_set(f"{year} test", d, models, thr, ev[year], rng)
        res[f"test_{year}"]["subgroup_age_75_plus_M"] = subgroup_age75(d, models, thr, ev[year], rng)
        if year == 2025:
            red = d[~d["excluded"]].assign(p=models["M_hybrid_core25"].predict(d[~d["excluded"]]))
            red = red[red["p"] >= thr["M_hybrid_core25"]["red_threshold"]].head(5)
            res["example_reasons_2025"] = [{"patient_id": r.patient_id, "day": int(r.day), "risk": round(float(r.p), 3),
                                            "reasons": rs} for r, rs in zip(red.itertuples(), top_reasons(
                                                boosters["M"], red[list(CORE)]), strict=True)]
        del d
    res["seconds"] = round(time.time() - t0)
    (REPORTS_DIR / f"fastclock_eval_{regime}.json").write_text(json.dumps(res, indent=2, default=float),
                                                              encoding="utf-8")
    return res


def g3(res: dict, res_matched: dict | None) -> dict:
    it = res["internal_test_2024"]
    m = it["M_hybrid_core25"]["day_level"]
    beats = {b: bool(m["auprc"] > it[b]["day_level"]["auprc"]) for b in BASELINES_G3}
    lead = it["M_hybrid_core25"]["alerts"]["lead_time"]
    out = {
        "rule": "Amendment 1 A1.4: the fast clock always leads. Hybrid M leads if it beats B0, B1 and B2 on mismatched "
                "AUPRC (2024 internal-test patients); otherwise B4 (twin physics risk) + transparent rules lead.",
        "decision_set": "2024 internal-test patients (never used for fitting, early stopping, calibration or "
                        "thresholds)",
        "auprc": {k: {"value": it[k]["day_level"]["auprc"], "ci95": it[k]["day_level"]["auprc_ci95"]}
                  for k in it if not k.startswith("_")},
        "M_beats": beats, "paired_difference_M_minus": it["_paired_auprc_difference_M_minus"],
        "M_beats_B3_plain_lightgbm": bool(m["auprc"] > it["B3_lightgbm_raw"]["day_level"]["auprc"]),
        "if_M_does_not_beat_B3": "EVAL_PLAN 15.5: we say so and argue from robustness and the what-if capability",
        "lead_model": "M_hybrid_core25" if all(beats.values()) else "B4_twin_physics_risk + transparent rules",
        "lead_time_M_internal_test": lead,
        "lead_time_target_A1_3": {
            "target": "median lead >= 24 h on episodes whose trigger began >= 24 h before onset",
            "median_h_trigger_ge_24h": lead["by_trigger_gap"]["trigger_ge_24h"]["median_lead_h"],
            "met": bool((lead["by_trigger_gap"]["trigger_ge_24h"]["median_lead_h"] or 0) >= 24)},
        "operational_M": {s_: {k: res[s_]["M_hybrid_core25"]["alerts"].get(k) for k in (
            "red_per_100_patient_days", "red_days_per_100_patient_days", "sensitivity_red", "sensitivity_red_ci95",
            "alerts_per_aki_caught_red", "alerts_per_aki_caught_red_ci95", "sensitivity_amber_or_red",
            "amber_plus_red_per_100_patient_days", "ppv_red_alert", "ppv_red_day", "ppv_ceiling_red_day",
            "ppv_red_day_at_1_10_prevalence", "ppv_red_day_at_1_50_prevalence")}
            for s_ in ("internal_test_2024", "test_2025", "test_2026") if s_ in res},
        "held_out_seasons": {y: {k: {"auprc": res[f"test_{y}"][k]["day_level"]["auprc"],
                                     "auprc_ci95": res[f"test_{y}"][k]["day_level"]["auprc_ci95"],
                                     "sensitivity_red": res[f"test_{y}"][k]["alerts"]["sensitivity_red"],
                                     "red_per_100_patient_days": res[f"test_{y}"][k]["alerts"][
                                         "red_per_100_patient_days"]}
                                 for k in res[f"test_{y}"] if not k.startswith("_") and k != "subgroup_age_75_plus_M"}
                             for y in (2025, 2026) if f"test_{y}" in res},
    }
    if res_matched is not None:
        out["matched_regime_internal_test_auprc"] = {
            k: res_matched["internal_test_2024"][k]["day_level"]["auprc"]
            for k in res_matched["internal_test_2024"] if not k.startswith("_")}
    return out


def _load_eval(regime: str) -> dict | None:
    f = REPORTS_DIR / f"fastclock_eval_{regime}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--regimes", nargs="*", default=["mismatched", "matched"])
    a = ap.parse_args()
    rng = np.random.default_rng(SEED)
    assert not any(c in CORE for c in LABEL_COLS)
    res = run("mismatched", rng) if "mismatched" in a.regimes else _load_eval("mismatched")
    res_m = run("matched", rng) if "matched" in a.regimes else _load_eval("matched")
    if res is not None:
        dec = g3(res, res_m)
        (REPORTS_DIR / "g3_decision.json").write_text(json.dumps(dec, indent=2, default=float), encoding="utf-8")
        print(json.dumps({k: dec[k] for k in ("auprc", "M_beats", "lead_model")}, indent=1, default=float))
    return 0


if __name__ == "__main__":
    sys.exit(main())
