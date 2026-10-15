"""L1 calibration target with uncertainty (Decisions v1 item 10): triple vs double therapy within antihypertensive
(ACEi/ARB + diuretic) users, per season and pooled over 2024-2026, with a patient-level bootstrap 95 % CI.

One season has only ~15-25 AKI events on triple-therapy days, so a single-season RR is very noisy; the pooled
estimate is the one compared with the pass band 1.1-2.5 (Lapi BMJ 2013: 1.31 overall, 1.82 in the first 30 days;
all our NSAID courses are new). Reads data/synthetic/<year>/mismatched/ and writes reports/l1_pooled.json.
"""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from vrikka.config import DATA_DIR, REPORTS_DIR, SEED

SYN = DATA_DIR / "synthetic"


def table(years) -> pd.DataFrame:
    pp = pd.read_parquet(SYN / "patients_public.parquet")
    both = pp["on_ras"] & pp["diuretic"].map(lambda x: isinstance(x, str) and bool(x))
    ids = set(pp.loc[both, "patient_id"])
    out = []
    for y in years:
        t = pd.read_parquet(
            SYN / str(y) / "mismatched" / "truth_daily.parquet", columns=["patient_id", "day", "y", "excluded"]
        )
        e = pd.read_parquet(
            SYN / str(y) / "events_daily.parquet", columns=["patient_id", "day", "nsaid_on", "adherent"]
        )
        d = t.merge(e, on=["patient_id", "day"])
        d = d[d.patient_id.isin(ids) & ~d.excluded & d.adherent].sort_values(["patient_id", "day"])
        d["recent"] = (
            d.groupby("patient_id")["nsaid_on"].transform(lambda s: s.rolling(4, min_periods=1).max()).astype(bool)
        )
        d["grp"] = np.where(d.nsaid_on, "triple", np.where(~d.recent, "double", "other"))
        d["season"] = y
        out.append(d[d.grp != "other"][["patient_id", "season", "grp", "y"]])
    return pd.concat(out)


def rr(df: pd.DataFrame) -> tuple[float, int]:
    g = df.groupby("grp")["y"].agg(["sum", "count"])
    return float(
        (g.loc["triple", "sum"] / g.loc["triple", "count"]) / (g.loc["double", "sum"] / g.loc["double", "count"])
    ), int(g.loc["triple", "sum"])


def boot(df: pd.DataFrame, n: int, rng) -> tuple[float, float]:
    by = {p: g for p, g in df.groupby("patient_id")}
    pids = np.array(list(by))
    vals = [rr(pd.concat([by[p] for p in rng.choice(pids, pids.size)]))[0] for _ in range(n)]
    return tuple(np.round(np.percentile(vals, [2.5, 97.5]), 2))


def main() -> int:
    rng = np.random.default_rng(SEED)
    d = table((2024, 2025, 2026))
    res = {
        "definition": "AKI onset within 72 h; triple = ACEi/ARB + diuretic + NSAID that day; double = ACEi/ARB + "
        "diuretic, no NSAID in the last 4 days; adherent, non-excluded days",
        "pass_band": [1.1, 2.5],
        "per_season": {},
    }
    for y in (2024, 2025, 2026):
        est, ev = rr(d[d.season == y])
        res["per_season"][str(y)] = {"rr": round(est, 2), "ci95": boot(d[d.season == y], 400, rng), "triple_events": ev}
    est, ev = rr(d)
    res["pooled"] = {
        "rr": round(est, 2),
        "ci95": boot(d, 400, rng),
        "triple_events": ev,
        "pass": bool(1.1 <= est <= 2.5),
    }
    (REPORTS_DIR / "l1_pooled.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
