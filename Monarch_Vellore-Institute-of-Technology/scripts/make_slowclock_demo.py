"""Slow-clock ranges for the fictional demo personas -> reports/slowclock_demo.json (Part 5).

Every slow-clock number the UI, README or slides quote for the personas comes from this file. Personas have no serial
eGFR, so the slow clock uses the baseline eGFR as its only observation and the registry prior for the persona's
group: the ranges are wide, which is the honest answer without serial labs. Scenarios: continue as is; one stage-1
kidney injury this season (associated-with penalty, applied once, fading); starting an SGLT2 inhibitor (for people
not already on one).
"""
from __future__ import annotations

import json
import sys

import numpy as np

from vrikka.config import REPORTS_DIR, load_yaml, param
from vrikka.physiology.equations import creatinine_from_egfr
from vrikka.slowclock.bayes_slope import fit
from vrikka.slowclock.kfre import kfre_panel
from vrikka.slowclock.projection import AkiEpisode, Scenario, compare, project, wording

AKI_THIS_SEASON_YEARS = 0.1         # an episode about five weeks from now (within the current heat season)


def scenarios(on_sglt2i: bool) -> list[Scenario]:
    out = [Scenario(label="continue as is"),
           Scenario(episodes=[AkiEpisode(AKI_THIS_SEASON_YEARS, 1)], label="one stage-1 kidney injury this season")]
    if not on_sglt2i:
        out.append(Scenario(sglt2i_start_years=0.0, label="start an SGLT2 inhibitor now"))
    return out


def rnd(x: float) -> float | None:
    return None if not np.isfinite(x) else round(float(x), 1)


def persona(name: str, cfg: dict) -> dict:
    p, h = cfg["person"], cfg.get("history", {})
    post = fit([(0.0, float(p["egfr"]))], egfr_now=float(p["egfr"]), dm=bool(h.get("dm")),
               uacr_mg_g=h.get("uacr_mg_g"))
    on_sglt2i = bool(cfg.get("chronic", {}).get("sglt2"))
    rows = {}
    base = None
    for sc in scenarios(on_sglt2i):
        pr = project(post, sc)
        idx = {y: int(np.argmin(np.abs(pr.t_years - y))) for y in (0, 5, 10)}
        rows[sc.label] = {
            "egfr_range_by_year": {str(y): [rnd(pr.low[i]), rnd(pr.median[i]), rnd(pr.high[i])]
                                   for y, i in idx.items()},
            "years_to": {k: {"low": rnd(v["low"]), "median": rnd(v["median"]), "high": rnd(v["high"]),
                             "text": v["text"]} for k, v in pr.years_to.items()},
        }
        if base is None:
            base = sc
        else:
            d = compare(post, base, sc)
            rows[sc.label]["difference_at_10y_vs_continue"] = {k: round(d[k], 1) for k in ("low", "median", "high")}
    return {
        "label": cfg["label"], "egfr_baseline": p["egfr"], "dm": bool(h.get("dm")), "prior_group": post.group,
        "slope_range_per_year": [round(x, 2) for x in post.slope_range()],
        "creatinine_baseline_mg_dl": round(creatinine_from_egfr(p["egfr"], p["age"], p["female"]), 3),
        "scenarios": rows,
        "kfre": kfre_panel(p["age"], not p["female"], p["egfr"], h.get("uacr_mg_g")),
        "wording_keys": wording(bool(h.get("dm")), has_aki_scenario=True),
    }


def main() -> int:
    sc = load_yaml("scenarios")
    out = {"note": "fictional personas; slow clock with the baseline eGFR as the only observation (no serial labs), "
                   "registry slope prior by group; 10-90 % ranges; the AKI penalty is 'associated with' (Trichy "
                   "diabetic kidney disease cohort, n = 274), applied once, fading, and 'extrapolated' without "
                   "diabetes",
           "band": [param("slow_band_low_q"), param("slow_band_high_q")], "draws": int(param("slow_mc_draws")),
           "aki_this_season_years": AKI_THIS_SEASON_YEARS,
           "personas": {name: persona(name, cfg) for name, cfg in sc.items()}}
    (REPORTS_DIR / "slowclock_demo.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    for name, v in out["personas"].items():
        c = v["scenarios"]["continue as is"]
        a = v["scenarios"]["one stage-1 kidney injury this season"]
        print(name, v["prior_group"], "eGFR@10y", c["egfr_range_by_year"]["10"], "AKI diff@10y",
              a["difference_at_10y_vs_continue"], "G4", c["years_to"]["g4"]["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
