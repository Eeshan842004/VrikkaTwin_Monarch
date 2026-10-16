"""Evaluation metrics for the fast clock (EVAL_PLAN §15.3; Amendment 1 A1.3, A1.5; Amendment 2 A2.5).

Day level (eligible patient-days): AUROC, AUPRC, Brier, calibration slope / intercept, within-patient AUROC, net
benefit.
Alert level (after hysteresis and 72-h de-duplication; vrikka.fastclock.alerts): notifications per 100 patient-days,
sensitivity per AKI episode, alerts per AKI caught ("number needed to alert"), PPV with its ceiling, PPV re-weighted
to 1/10 and 1/50 of the enriched prevalence (prior shift on the odds), and lead time split by trigger-to-onset gap.
Confidence intervals: patient-level bootstrap percentile intervals (1,000 resamples).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from vrikka.fastclock.alerts import AMBER, RED


# ------------------------------------------------------------------------------------------- weighted AP / AUROC
class RankCache:
    """Sort once; every bootstrap only re-weights rows (weight = how often the row's patient was drawn)."""

    def __init__(self, score: np.ndarray, y: np.ndarray):
        order = np.argsort(-score, kind="mergesort")
        self.order, self.y = order, y[order].astype(float)
        s = score[order]
        self.last = np.r_[np.nonzero(np.diff(s))[0], len(s) - 1]       # end of each tie group

    def ap_auc(self, w_sorted: np.ndarray) -> tuple[float, float]:
        tp = np.cumsum(w_sorted * self.y)[self.last]
        fp = np.cumsum(w_sorted * (1 - self.y))[self.last]
        P, Nn = tp[-1], fp[-1]
        if P <= 0 or Nn <= 0:
            return float("nan"), float("nan")
        rec = tp / P
        prec = tp / np.maximum(tp + fp, 1e-12)
        ap = float(np.sum(np.diff(np.r_[0.0, rec]) * prec))
        tpr, fpr = np.r_[0.0, rec], np.r_[0.0, fp / Nn]
        auc = float(np.sum(np.diff(fpr) * (tpr[1:] + tpr[:-1]) / 2))
        return ap, auc


def bootstrap_counts(n_patients: int, n_boot: int, rng) -> np.ndarray:
    """(n_boot, n_patients) multiplicities of a patient-level bootstrap."""
    return np.stack([np.bincount(rng.integers(0, n_patients, n_patients), minlength=n_patients)
                     for _ in range(n_boot)])


def ci(vals) -> list[float]:
    v = np.asarray(vals, dtype=float)
    v = v[np.isfinite(v)]
    return [round(float(x), 4) for x in np.percentile(v, [2.5, 97.5])] if v.size else [float("nan")] * 2


# ------------------------------------------------------------------------------------------- day-level metrics
def calibration_slope_intercept(p: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    lp = np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))
    m = LogisticRegression(C=1e6, max_iter=1000).fit(lp.reshape(-1, 1), y.astype(int))
    return float(m.coef_[0, 0]), float(m.intercept_[0])


def within_patient_auroc(pid: np.ndarray, p: np.ndarray, y: np.ndarray) -> float:
    """Mean over patients with both dangerous and safe days of the AUROC among that patient's own days."""
    df = pd.DataFrame({"pid": pid, "p": p, "y": y.astype(int)})
    g = df.groupby("pid")["y"].agg(["sum", "count"])
    keep = g.index[(g["sum"] > 0) & (g["sum"] < g["count"])]
    d = df[df["pid"].isin(keep)].copy()
    if d.empty:
        return float("nan")
    d["r"] = d.groupby("pid")["p"].rank(method="average")
    d["rpos"] = d["r"] * d["y"]
    s = d.groupby("pid").agg(rs=("rpos", "sum"), n1=("y", "sum"), n=("y", "count"))
    n0 = s["n"] - s["n1"]
    return float(((s["rs"] - s["n1"] * (s["n1"] + 1) / 2) / (s["n1"] * n0)).mean())


def net_benefit(p: np.ndarray, y: np.ndarray, thresholds=(0.05, 0.10, 0.15, 0.20)) -> dict:
    n = len(y)
    out = {}
    for t in thresholds:
        pos = p >= t
        tp, fp = float((pos & (y == 1)).sum()), float((pos & (y == 0)).sum())
        out[f"{t:.2f}"] = {"model": round(tp / n - fp / n * t / (1 - t), 6),
                           "treat_all": round(float(y.mean()) - (1 - float(y.mean())) * t / (1 - t), 6)}
    return out


def day_metrics(df: pd.DataFrame, p: np.ndarray, boots: np.ndarray) -> dict:
    """df: eligible rows with patient_id and y; p: calibrated probabilities; boots: (B, n_patients) multiplicities over
    ``pd.factorize(df.patient_id)`` codes (shared across models so model differences are paired)."""
    y = df["y"].to_numpy(bool)
    codes, _ = pd.factorize(df["patient_id"])
    rc = RankCache(p, y)
    ap, auc = rc.ap_auc(np.ones(len(y)))
    ap_b, auc_b = zip(*(rc.ap_auc(b[codes][rc.order].astype(float)) for b in boots), strict=True)
    slope, inter = calibration_slope_intercept(p, y)
    return {"rows": int(len(y)), "positive_days": int(y.sum()), "prevalence": round(float(y.mean()), 5),
            "auprc": round(ap, 4), "auprc_ci95": ci(ap_b), "auroc": round(auc, 4), "auroc_ci95": ci(auc_b),
            "brier": round(float(np.mean((p - y) ** 2)), 6), "calibration_slope": round(slope, 3),
            "calibration_intercept": round(inter, 3),
            "within_patient_auroc": round(within_patient_auroc(df["patient_id"].to_numpy(), p, y), 4),
            "net_benefit": net_benefit(p, y.astype(int)), "_boot_ap": np.array(ap_b)}


# ------------------------------------------------------------------------------------------- alert-level metrics
def to_grid(df: pd.DataFrame, col: str, fill) -> np.ndarray:
    """Long rows -> (patients sorted by id, days) float grid; missing cells get ``fill``."""
    return df.pivot(index="patient_id", columns="day", values=col).sort_index().to_numpy(dtype=float,
                                                                                        na_value=float(fill))


def episode_table(df: pd.DataFrame, events: pd.DataFrame | None) -> pd.DataFrame:
    """One row per AKI episode (episode_start) with its trigger-to-onset gap (true events; evaluation only)."""
    ep = df.loc[df["episode_start"].astype(bool), ["patient_id", "day"]].rename(columns={"day": "onset_day"})
    if events is None or ep.empty:
        ep["gap"] = "unknown"
        return ep
    ev = events[["patient_id", "day", "fever_excess_c", "vomit_episodes", "diarrhoea_episodes", "nsaid_on"]].copy()
    ev["trig"] = (ev["fever_excess_c"] > 0) | (ev["vomit_episodes"] > 0) | (ev["diarrhoea_episodes"] > 0) | \
        ev["nsaid_on"].astype(bool)
    ev = ev.sort_values(["patient_id", "day"])
    ev["start"] = ev["trig"] & ~ev.groupby("patient_id")["trig"].shift(1, fill_value=False)
    starts = ev.loc[ev["start"], ["patient_id", "day"]]
    m = ep.merge(starts, on="patient_id", how="left")
    m = m[(m["day"] <= m["onset_day"]) & (m["day"] >= m["onset_day"] - 7)]
    last = m.groupby(["patient_id", "onset_day"])["day"].max().rename("trigger_day").reset_index()
    ep = ep.merge(last, on=["patient_id", "onset_day"], how="left")
    ep["gap"] = np.where(ep["trigger_day"].isna(), "no_sick_day_trigger",
                         np.where(ep["trigger_day"] <= ep["onset_day"] - 1, "trigger_ge_24h", "trigger_lt_24h"))
    return ep


def gap_row(E: pd.DataFrame, caught: pd.DataFrame, g: str) -> dict:
    sub = caught[caught["gap"] == g]
    return {"episodes": int((E["gap"] == g).sum()), "caught_red": int(len(sub)),
            "median_lead_h": float(np.median(sub["lead_h"])) if len(sub) else None}


def alert_metrics(df: pd.DataFrame, p: np.ndarray, st: dict, events: pd.DataFrame | None, rng,
                  n_boot: int = 1000) -> dict:
    """df: ALL rows of the season (eligible and excluded), p aligned to df; st = alerts.alert_states on the grid."""
    pids = np.sort(df["patient_id"].unique())
    pidx = {p_: i for i, p_ in enumerate(pids)}
    elig = ~to_grid(df, "excluded", True).astype(bool)
    y = to_grid(df.assign(yy=df["y"].astype(float)), "yy", 0.0).astype(bool) & elig
    level, red_r, amb_r = st["level"], st["red_raised"], st["amber_raised"]
    D = elig.shape[1]
    ep = episode_table(df, events)
    rows = []
    for r in ep.itertuples(index=False):
        i, o = pidx[r.patient_id], int(r.onset_day)
        win = [d for d in range(max(o - 3, 0), o) if elig[i, d]]
        if not win:
            continue
        red_days = [d for d in win if level[i, d] == RED]
        amb_days = [d for d in win if level[i, d] >= AMBER]
        lead = None
        if red_days:
            first = red_days[0]
            while first - 1 >= 0 and level[i, first - 1] == RED:
                first -= 1
            lead = 24 * (o - first) - 1
        rows.append((i, bool(red_days), bool(amb_days), lead, r.gap))
    E = pd.DataFrame(rows, columns=["i", "red", "amber", "lead_h", "gap"])
    n = len(pids)
    per = pd.DataFrame({
        "elig": elig.sum(1), "red_alerts": red_r.sum(1), "amber_alerts": amb_r.sum(1),
        "red_alert_true": (red_r & y).sum(1), "red_days": ((level == RED) & elig).sum(1),
        "red_days_pos": ((level == RED) & y).sum(1), "pos_days": y.sum(1),
        "ambplus_days": ((level >= AMBER) & elig).sum(1), "ambplus_days_pos": ((level >= AMBER) & y).sum(1),
    })
    per["episodes"] = np.bincount(E["i"], minlength=n) if len(E) else 0
    per["caught_red"] = np.bincount(E["i"], weights=E["red"].astype(float), minlength=n) if len(E) else 0
    per["caught_amber"] = np.bincount(E["i"], weights=E["amber"].astype(float), minlength=n) if len(E) else 0
    A = per.to_numpy(dtype=float)
    cols = {c: j for j, c in enumerate(per.columns)}

    def summary(tot: np.ndarray) -> dict:
        g = {c: tot[j] for c, j in cols.items()}
        neg_days = g["elig"] - g["pos_days"]
        sens_day = g["red_days_pos"] / max(g["pos_days"], 1)
        spec_day = 1 - (g["red_days"] - g["red_days_pos"]) / max(neg_days, 1)
        prev = g["pos_days"] / max(g["elig"], 1)
        out = {
            "red_per_100_patient_days": 100 * g["red_alerts"] / max(g["elig"], 1),
            "amber_plus_red_per_100_patient_days": 100 * (g["red_alerts"] + g["amber_alerts"]) / max(g["elig"], 1),
            "sensitivity_red": g["caught_red"] / max(g["episodes"], 1),
            "sensitivity_amber_or_red": g["caught_amber"] / max(g["episodes"], 1),
            "alerts_per_aki_caught_red": g["red_alerts"] / max(g["caught_red"], 1),
            "alerts_per_aki_caught_amber_plus_red": (g["red_alerts"] + g["amber_alerts"])
            / max(g["caught_amber"], 1),
            "ppv_red_alert": g["red_alert_true"] / max(g["red_alerts"], 1),
            "ppv_red_day": g["red_days_pos"] / max(g["red_days"], 1),
            "ppv_ceiling_red_day": min(1.0, g["pos_days"] / max(g["red_days"], 1)),
            "day_sensitivity_red": sens_day, "day_specificity_red": spec_day, "prevalence": prev,
        }
        for f in (10, 50):
            pp = prev / f
            den = max(sens_day * pp + (1 - spec_day) * (1 - pp), 1e-12)
            out[f"ppv_red_day_at_1_{f}_prevalence"] = sens_day * pp / den
        return out

    point = summary(A.sum(0))
    boots = bootstrap_counts(n, n_boot, rng)
    bs = [summary(b @ A) for b in boots]
    res = {"episodes_with_a_prediction_window": int(len(E)), "patient_days": int(elig.sum()), "days": D}
    for k, v in point.items():
        res[k] = round(float(v), 5)
        res[f"{k}_ci95"] = ci([b[k] for b in bs])
    caught = E[E["red"]]
    res["lead_time"] = {
        "median_h_all_caught": None if caught.empty else float(np.median(caught["lead_h"])),
        "pct_caught_ge_24h_ahead": None if caught.empty else round(100 * float((caught["lead_h"] >= 24).mean()), 1),
        "by_trigger_gap": {g: gap_row(E, caught, g) for g in ("trigger_ge_24h", "trigger_lt_24h",
                                                               "no_sick_day_trigger")},
        "note": "first red at 09:00 the day before an 08:00 onset = 23 h lead; the 72-h horizon caps it at 71 h",
    }
    return res
