"""Doctor Triage demo panel -> reports/demo_triage_panel.json (Part 7).

Synthetic patients of the held-out 2025 test season (mismatched world), scored by the FROZEN hybrid model M with its
frozen isotonic map, thresholds, hysteresis and de-duplication (fastclock/frozen.py, fastclock/alerts.py). Scoring
held-out data with a frozen model for display is not tuning: nothing is refitted. The demo day is the day with the most
patients in the red state; the panel keeps every red patient on that day (up to a cap), the highest ambers and a
random sample of greens. For each patient: public EHR fields, the 14-day risk trajectory, the top-3 reasons
(LightGBM pred_contrib), labs (with the "not reliable while creatinine is changing" tag), steps / sleep, KFRE where
valid, slow-clock ranges from the patient's stable labs, and - hidden from the model, shown only behind a "reveal"
toggle - whether the simulation produced a kidney injury in the next 72 hours.
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from vrikka.config import DATA_DIR, REPORTS_DIR, SEED, param
from vrikka.fastclock import frozen
from vrikka.fastclock.alerts import AMBER, RED, alert_states
from vrikka.fastclock.display import lab_egfr_status, risk_text
from vrikka.fastclock.features import CORE
from vrikka.physiology.equations import egfr_ckd_epi_2021
from vrikka.slowclock.bayes_slope import fit_from_labs
from vrikka.slowclock.kfre import kfre_panel
from vrikka.slowclock.projection import project

YEAR, REGIME = 2025, "mismatched"
N_RED, N_AMBER, N_GREEN, HISTORY = 12, 10, 8, 14
WARMUP_DAYS = 14      # every twin starts from population priors on 1 March; the demo day is chosen after warm-up
LEVEL = {0: "green", 1: "amber", 2: "red"}


def generics(r) -> list[str]:
    out = []
    if r.on_ras:
        out.append("telmisartan" if r.ras_kind == "arb" else "ramipril")
    if isinstance(r.diuretic, str) and r.diuretic:
        out.append(r.diuretic)
    if r.on_mra:
        out.append("spironolactone")
    if r.on_sglt2i:
        out.append("empagliflozin")
    if r.on_metformin:
        out.append("metformin")
    if r.on_ccb:
        out.append("amlodipine")
    if r.beta_blocker:
        out.append("metoprolol")
    return out


def main() -> int:
    f = DATA_DIR / "features" / f"{YEAR}_{REGIME}.parquet"
    if not f.exists():
        print(f"missing {f}; run scripts/build_features.py --years {YEAR} --regimes {REGIME}")
        return 1
    df = pd.read_parquet(f).sort_values(["patient_id", "day"]).reset_index(drop=True)
    for c in ("y", "excluded"):
        df[c] = df[c].astype(bool)
    df["p"] = frozen.predict(df, "M_hybrid_core25", REGIME)
    thr = frozen.thresholds(REGIME)["M_hybrid_core25"]
    ids = np.sort(df["patient_id"].unique())
    P = df.pivot(index="patient_id", columns="day", values="p").loc[ids].to_numpy(float)
    E = ~df.pivot(index="patient_id", columns="day", values="excluded").loc[ids].to_numpy(bool)
    st = alert_states(np.nan_to_num(P), E, thr["red_threshold"], thr["amber_threshold"])
    lv = st["level"]
    red_per_day = ((lv == RED) & E).sum(axis=0)
    day = WARMUP_DAYS + int(np.argmax(red_per_day[WARMUP_DAYS:]))
    rng = np.random.default_rng(SEED)
    red = ids[(lv[:, day] == RED) & E[:, day]]
    amb = ids[(lv[:, day] == AMBER) & E[:, day]]
    grn = ids[(lv[:, day] < AMBER) & E[:, day]]
    p_day = pd.Series(P[:, day], index=ids)
    chosen = (list(p_day[red].sort_values(ascending=False).index[:N_RED])
              + list(p_day[amb].sort_values(ascending=False).index[:N_AMBER])
              + list(rng.choice(grn, size=min(N_GREEN, len(grn)), replace=False)))
    pub = pd.read_parquet(DATA_DIR / "synthetic" / "patients_public.parquet").set_index("patient_id")
    labs = pd.read_parquet(DATA_DIR / "synthetic" / str(YEAR) / REGIME / "labs.parquet")
    weather_dates = pd.date_range(f"{YEAR}-03-01", periods=lv.shape[1], freq="D")
    rows = df[(df["day"] == day) & df["patient_id"].isin(chosen)].set_index("patient_id")
    reasons = dict(zip(rows.index, frozen.reasons(rows[list(CORE)].reset_index(drop=True)), strict=True))
    pidx = {p: i for i, p in enumerate(ids)}
    out = []
    for pid in chosen:
        r, x = pub.loc[pid], rows.loc[pid]
        i = pidx[pid]
        hist = df[(df["patient_id"] == pid) & (df["day"] > day - HISTORY) & (df["day"] <= day)]
        pl = labs[(labs["patient_id"] == pid) & (labs["day"] <= day)].sort_values("day")
        lab_series = [(float(d) / 365.25 - day / 365.25, float(c)) for d, c in zip(pl["day"], pl["creatinine_mg_dl"],
                                                                                  strict=True)]
        last = pl.iloc[-1]
        stable = pl[pl["reason"] == "pre_season"]["creatinine_mg_dl"].iloc[-1]
        status = lab_egfr_status(float(last["creatinine_mg_dl"]), float(stable))
        post = fit_from_labs(lab_series, float(r["age"]), bool(r["female"]), bool(r["dm"]), float(r["uacr_mg_g"]),
                             egfr_fallback=float(r["egfr_baseline"]))
        pr = project(post)
        j10 = int(np.argmin(np.abs(pr.t_years - param("projection_years"))))
        p = float(x["p"])
        out.append({
            "patient_id": pid, "label": f"Synthetic patient {pid} (fictional)", "age": int(r["age"]),
            "female": bool(r["female"]), "city": r["city"], "language": r["language"], "occupation": r["occupation"],
            "tier": r["tier"], "dm": bool(r["dm"]), "htn": bool(r["htn"]), "ckd_g3": bool(r["ckd_g3"]),
            "heart_failure": bool(r["heart_failure"]), "egfr_baseline": float(r["egfr_baseline"]),
            "cr_baseline": float(r["cr_baseline"]), "uacr_mg_g": float(r["uacr_mg_g"]),
            "last_potassium": float(r["potassium_mmol_l"]), "cyp2c9": r["cyp2c9_genotype"], "generics": generics(r),
            "risk": p, "risk_text": risk_text(p)["text"], "level": LEVEL[int(lv[i, day])],
            "reasons": [z["i18n_key"] for z in reasons[pid]],
            "reason_contributions": [round(z["contribution"], 3) for z in reasons[pid]],
            "trajectory": {"days": hist["day"].tolist(),
                           "dates": [str(weather_dates[d].date()) for d in hist["day"]],
                           "risk": [round(float(v), 5) for v in hist["p"]],
                           "level": [LEVEL[int(lv[i, d])] for d in hist["day"]],
                           "steps": [None if not np.isfinite(v) else int(v) for v in hist["steps"]],
                           "sleep_h": [None if not np.isfinite(v) else round(float(v), 1) for v in hist["sleep_h"]],
                           "wt_vs_dry_kg": [None if not np.isfinite(v) else round(float(v), 2)
                                            for v in hist["wt_vs_dry_kg"]],
                           "hr_delta_bpm": [None if not np.isfinite(v) else round(float(v), 1)
                                            for v in hist["hr_delta_bpm"]]},
            "twin": {"mc_risk_72h": round(float(x["mc_risk_72h"]), 3), "gfr_frac": round(float(x["tw_gfr_frac"]), 3),
                     "cr_ratio": round(float(x["tw_cr_ratio"]), 3), "theta": round(float(x["tw_theta"]), 3)},
            "last_lab": {"day": int(last["day"]), "creatinine_mg_dl": round(float(last["creatinine_mg_dl"]), 3),
                         "egfr": round(float(egfr_ckd_epi_2021(float(last["creatinine_mg_dl"]), float(r["age"]),
                                                               bool(r["female"]))), 1),
                         "reliable": status["reliable"], "tag_key": status["tag_key"], "reason": last["reason"]},
            "kfre": kfre_panel(float(r["age"]), not bool(r["female"]), float(r["egfr_baseline"]),
                               float(r["uacr_mg_g"])),
            "slow_clock": {"prior_group": post.group, "stable_labs_used": post.n_obs,
                           "slope_range_per_year": [round(v, 2) for v in post.slope_range()],
                           "egfr_10y_range": [round(float(pr.low[j10]), 1), round(float(pr.median[j10]), 1),
                                              round(float(pr.high[j10]), 1)],
                           "years_to": {k: v["text"] for k, v in pr.years_to.items()}},
            "truth_hidden": {"aki_onset_within_72h": bool(x["y"]),
                             "note": "simulation truth, never seen by the model; shown only behind the reveal toggle"},
        })
    meta = {
        "source": f"held-out {YEAR} test season, {REGIME} (headline) world; synthetic patients (fictional)",
        "model": "frozen hybrid model M (Part 4): frozen isotonic map, thresholds, hysteresis and 72-h de-duplication",
        "demo_day": day, "demo_date": str(weather_dates[day].date()), "warmup_days_excluded": WARMUP_DAYS,
        "red_state_on_day_0": int(((lv[:, 0] == RED) & E[:, 0]).sum()),
        "red_state_per_day_median_after_warmup": float(np.median(red_per_day[WARMUP_DAYS:])),
        "patients_in_red_state_that_day": int(((lv[:, day] == RED) & E[:, day]).sum()),
        "patients_in_amber_state_that_day": int(((lv[:, day] == AMBER) & E[:, day]).sum()),
        "eligible_patients_that_day": int(E[:, day].sum()),
        "red_threshold": thr["red_threshold"], "amber_threshold": thr["amber_threshold"],
        "panel": {"red": int(min(N_RED, len(red))), "amber": int(min(N_AMBER, len(amb))),
                  "green": int(min(N_GREEN, len(grn)))},
        "panel_red_with_aki_within_72h": int(sum(o["truth_hidden"]["aki_onset_within_72h"] for o in out
                                                 if o["level"] == "red")),
    }
    (REPORTS_DIR / "demo_triage_panel.json").write_text(json.dumps({**meta, "patients": out}, indent=1),
                                                        encoding="utf-8")
    print(json.dumps(meta, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
