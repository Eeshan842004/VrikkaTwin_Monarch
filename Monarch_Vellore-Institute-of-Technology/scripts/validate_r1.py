"""Real-data checks R1a and R1b on the MIMIC-IV demo and the eICU-CRD demo (EVAL_PLAN §15.1, Amendment 1 A1.7).

HELD-OUT (Amendment 2 A2.2): neither check informs any parameter.

R1a, "labelling verified against the official mimic-code KDIGO SQL": our ``kdigo_stage()`` applied to each ICU stay's
creatinine series (mimiciv_derived.kdigo_creatinine) vs mimic-code's creatinine-only stage ``aki_stage_creat``.
Pass: >= 99 % agreement. A correctness check of our labelling code, not a validation of predictions.

R1b, "our creatinine equation tracks real patients": a 24-hour-ahead creatinine forecast from a one-state Kalman filter
on log GFR whose measurement model is the SAME kinetics function the twin uses (``renal.creatinine_step``), compared
with last-value carry-forward and a linear trend through the last two values. Steady state is assumed at each stay's
first creatinine (G = eGFR x Cr / 100, Vd = total body water from weight / sex / age). Pairs: every measurement with a
later one 18-30 h ahead (the one closest to 24 h). Excluded: MIMIC stays with any CRRT record; eICU stays whose
admission diagnosis mentions dialysis or end-stage renal disease (the eICU demo has no treatment table, so this is a
proxy). The filter settings were fixed in the registry before this ran. Reported as it comes out, whichever method
wins, with stay-level bootstrap CIs.

Writes reports/r1_validation.json.
"""
from __future__ import annotations

import json
import sys

import duckdb
import numpy as np
import pandas as pd

from vrikka.config import DATA_DIR, REPORTS_DIR, SEED, param
from vrikka.physiology.equations import egfr_ckd_epi_2021, kdigo_stage
from vrikka.physiology.renal import creatinine_step

DB = DATA_DIR / "raw" / "validation.duckdb"
METHODS = ("kinetic_filter", "carry_forward", "linear_trend")


def hours(ts: pd.Series) -> np.ndarray:
    return ((pd.to_datetime(ts) - pd.Timestamp("2000-01-01")).dt.total_seconds() / 3600).to_numpy(float)


def r1a(con) -> dict:
    cr = con.execute("SELECT stay_id, charttime, creat FROM mimiciv_derived.kdigo_creatinine "
                     "WHERE creat IS NOT NULL ORDER BY stay_id, charttime").df()
    ref = con.execute("SELECT stay_id, charttime, aki_stage_creat FROM mimiciv_derived.kdigo_stages "
                      "WHERE creat IS NOT NULL").df()
    rows = []
    for sid, g in cr.groupby("stay_id"):
        t, c = hours(g["charttime"]), g["creat"].to_numpy(float)
        rows += [(sid, g["charttime"].iat[i], kdigo_stage(t, c, i)) for i in range(len(g))]
    ours = pd.DataFrame(rows, columns=["stay_id", "charttime", "ours"])
    m = ours.merge(ref, on=["stay_id", "charttime"], how="inner")
    theirs = m["aki_stage_creat"].fillna(0).astype(int)
    agree = m["ours"] == theirs
    tab = pd.crosstab(m["ours"], theirs)
    return {
        "label": "labelling verified against the official mimic-code KDIGO SQL (creatinine-only stage)",
        "values_compared": int(len(m)), "stays": int(m["stay_id"].nunique()),
        "agreement_pct": round(100 * float(agree.mean()), 2), "pass_threshold_pct": 99.0,
        "pass": bool(agree.mean() >= 0.99),
        "confusion_rows_ours_cols_mimic_code": {str(i): {str(j): int(tab.loc[i, j]) for j in tab.columns}
                                                for i in tab.index},
        "disagreements_first_10": m[~agree].head(10).astype(str).to_dict("records"),
    }


def mimic_series(con) -> tuple[pd.DataFrame, int]:
    crrt = set(con.execute("SELECT DISTINCT stay_id FROM mimiciv_derived.crrt").df()["stay_id"])
    cr = con.execute("""
        SELECT k.stay_id, k.charttime, k.creat, p.gender, p.anchor_age AS age, w.weight
        FROM mimiciv_derived.kdigo_creatinine k
        JOIN mimiciv_icu.icustays i ON i.stay_id = k.stay_id
        JOIN mimiciv_hosp.patients p ON p.subject_id = i.subject_id
        LEFT JOIN (SELECT stay_id, AVG(weight) AS weight FROM mimiciv_derived.weight_durations GROUP BY stay_id) w
          ON w.stay_id = k.stay_id
        WHERE k.creat IS NOT NULL ORDER BY k.stay_id, k.charttime""").df()
    cr = cr[~cr["stay_id"].isin(crrt)].copy()
    cr["t_h"] = hours(cr["charttime"])
    cr["female"] = cr["gender"].eq("F")
    cr["unit"] = "mimic:" + cr["stay_id"].astype(str)
    return cr[["unit", "t_h", "creat", "female", "age", "weight"]], len(crrt)


def eicu_series(con) -> tuple[pd.DataFrame, int]:
    lab = con.execute("""
        SELECT l.patientunitstayid AS sid, l.labresultoffset / 60.0 AS t_h, l.labresult AS creat,
               p.gender, p.age, p.admissionweight AS weight, p.apacheadmissiondx AS dx
        FROM eicu.lab l JOIN eicu.patient p ON p.patientunitstayid = l.patientunitstayid
        WHERE lower(l.labname) = 'creatinine' AND l.labresult IS NOT NULL AND l.labresult > 0
              AND l.labresult <= 150""").df()
    excl = lab["dx"].fillna("").str.lower().str.contains("dialysis|end stage|end-stage|esrd")
    n_excl = int(lab.loc[excl, "sid"].nunique())
    lab = lab[~excl].copy()
    lab["age"] = pd.to_numeric(lab["age"].astype(str).replace("> 89", "90"), errors="coerce")
    lab["female"] = lab["gender"].eq("Female")
    lab = lab.groupby(["sid", "t_h"], as_index=False).agg(creat=("creat", "mean"), female=("female", "first"),
                                                          age=("age", "first"), weight=("weight", "first"))
    lab["unit"] = "eicu:" + lab["sid"].astype(str)
    return lab.sort_values(["unit", "t_h"])[["unit", "t_h", "creat", "female", "age", "weight"]], n_excl


def tbw_l(weight: float, female: bool, age: float) -> float:
    frac = param("tbw_frac_female") if female else param("tbw_frac_male")
    return (frac + (param("tbw_frac_young_bonus") if age < 60 else 0.0)) * weight


def forecast_pairs(g: pd.DataFrame) -> list[tuple[float, float, float, float]]:
    """(kinetic, carry-forward, linear trend, observed) for every value with a later one 18-30 h ahead."""
    t, c = g["t_h"].to_numpy(float), g["creat"].to_numpy(float)
    if len(t) < 3:
        return []
    age = float(g["age"].iat[0]) if pd.notna(g["age"].iat[0]) else 65.0
    female = bool(g["female"].iat[0])
    w0 = g["weight"].iat[0]
    w = float(w0) if pd.notna(w0) and 30 <= float(w0) <= 250 else 70.0
    vd = tbw_l(w, female, age) * 10.0
    gfr0 = float(egfr_ckd_epi_2021(c[0], age, female))
    gen = gfr0 * c[0] / 100.0
    th, var = np.log(gfr0), param("r1b_log_gfr_prior_sd") ** 2
    q_h = param("r1b_log_gfr_drift_sd_per_day") ** 2 / 24.0
    cv = param("cr_lab_cv")
    out = []
    for i in range(1, len(t)):
        dt = t[i] - t[i - 1]
        if dt <= 0:
            continue
        var += q_h * dt
        f0 = creatinine_step(c[i - 1], gen, float(np.exp(th)), vd, dt)
        eps = 1e-4
        jac = (creatinine_step(c[i - 1], gen, float(np.exp(th + eps)), vd, dt) - f0) / eps
        s = jac * var * jac + (cv * c[i]) ** 2 + (cv * c[i - 1]) ** 2
        k = var * jac / s
        th = float(np.clip(th + k * (c[i] - f0), np.log(1.0), np.log(250.0)))
        var = (1 - k * jac) * var
        later = np.nonzero((t > t[i] + 18) & (t <= t[i] + 30))[0]
        if later.size == 0:
            continue
        j = later[np.argmin(np.abs(t[later] - t[i] - 24))]
        h = t[j] - t[i]
        kin = creatinine_step(c[i], gen, float(np.exp(th)), vd, h)
        lin = max(c[i] + (c[i] - c[i - 1]) / dt * h, 0.1)
        out.append((kin, c[i], lin, c[j]))
    return out


def rmse_ci(err: dict[str, np.ndarray], units: list[str], rng, n: int = 1000) -> dict:
    groups = list(pd.Series(range(len(units))).groupby(pd.Series(units)).apply(np.array))
    point = {k: float(np.sqrt(np.mean(err[k] ** 2))) for k in METHODS}
    boot = {k: [] for k in METHODS}
    diff = []
    for _ in range(n):
        pick = np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])
        vals = {k: float(np.sqrt(np.mean(err[k][pick] ** 2))) for k in METHODS}
        for k in METHODS:
            boot[k].append(vals[k])
        diff.append(vals["kinetic_filter"] - min(vals["carry_forward"], vals["linear_trend"]))
    return {"rmse_mg_dl": {k: round(point[k], 4) for k in METHODS},
            "rmse_ci95": {k: [round(float(x), 4) for x in np.percentile(boot[k], [2.5, 97.5])] for k in METHODS},
            "kinetic_minus_best_simple_ci95": [round(float(x), 4) for x in np.percentile(diff, [2.5, 97.5])]}


def collect(df: pd.DataFrame) -> tuple[dict[str, np.ndarray], list[str]]:
    rows, units = [], []
    for u, g in df.groupby("unit", sort=False):
        for p in forecast_pairs(g):
            rows.append(p)
            units.append(u)
    a = np.array(rows) if rows else np.zeros((0, 4))
    return {"kinetic_filter": a[:, 0] - a[:, 3], "carry_forward": a[:, 1] - a[:, 3],
            "linear_trend": a[:, 2] - a[:, 3]}, units


def r1b(con, rng) -> dict:
    mimic, n_crrt = mimic_series(con)
    eicu, n_dx = eicu_series(con)
    res = {"label": "our creatinine equation tracks real patients (24 h-ahead creatinine forecast)",
           "excluded": {"mimic_stays_with_crrt": n_crrt, "eicu_stays_dialysis_or_esrd_diagnosis": n_dx},
           "settings": {"log_gfr_prior_sd": param("r1b_log_gfr_prior_sd"),
                        "log_gfr_drift_sd_per_day": param("r1b_log_gfr_drift_sd_per_day"),
                        "lab_cv": param("cr_lab_cv")}}
    pooled, pooled_units = {k: [] for k in METHODS}, []
    for name, df in (("mimic_iv_demo", mimic), ("eicu_demo", eicu)):
        err, units = collect(df)
        for k in METHODS:
            pooled[k].append(err[k])
        pooled_units += units
        res[name] = {"stays": int(df["unit"].nunique()), "stays_with_pairs": len(set(units)), "pairs": len(units),
                     **(rmse_ci(err, units, rng) if units else {})}
    allerr = {k: np.concatenate(v) for k, v in pooled.items()}
    res["pooled"] = {"pairs": len(pooled_units), "stays": len(set(pooled_units)),
                     **rmse_ci(allerr, pooled_units, rng)}
    r = res["pooled"]["rmse_mg_dl"]
    res["pooled"]["winner"] = min(r, key=r.get)
    res["pooled"]["kinetic_beats_carry_forward"] = bool(r["kinetic_filter"] < r["carry_forward"])
    return res


def main() -> int:
    con = duckdb.connect(str(DB), read_only=True)
    rng = np.random.default_rng(SEED)
    out = {"status": "held-out real-data checks (Amendment 2 A2.2)", "R1a": r1a(con), "R1b": r1b(con, rng)}
    (REPORTS_DIR / "r1_validation.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"R1a": {k: out["R1a"][k] for k in ("values_compared", "stays", "agreement_pct", "pass")},
                      "R1b": {k: out["R1b"][k] for k in ("excluded", "mimic_iv_demo", "eicu_demo", "pooled")}},
                     indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
