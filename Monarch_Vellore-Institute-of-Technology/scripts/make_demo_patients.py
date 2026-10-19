"""Demo personas S1-S6 (fictional) -> data/synthetic/demo_patients.json and reports/demo_numbers.json.

Every number the UI, slides or video quote about the demo personas comes from reports/demo_numbers.json
(Decisions v1 item 18). Old prototype numbers (2 / 32 / 7 / 1 / 47 %) are void.
Alert levels use the provisional thresholds (5 % / 15 %) until Part 4 tunes them to the alert budget.
"""
from __future__ import annotations

import json
import sys

from vrikka.config import DATA_DIR, REPORTS_DIR, load_yaml
from vrikka.twin.replay import replay

WHATIF_DAY = {"S1_riya": 8}


def main() -> int:
    sc = load_yaml("scenarios")
    demo, numbers = {}, {"note": "fictional personas; demo replay on real 2024 weather; truth = physiology engine; "
                                 "provisional alert thresholds 5 % / 15 % (tuned in Part 4)", "scenarios": {}}
    for name, cfg in sc.items():
        r = replay(name, cfg, whatif_day=WHATIF_DAY.get(name))
        demo[name] = {"label": cfg["label"], "person": cfg["person"], "chronic": cfg.get("chronic", {}),
                      "events": cfg.get("events", {}), "dates": r.dates}
        numbers["scenarios"][name] = {"label": cfg["label"], "expect": cfg["expect"], "summary": r.summary(),
                                      "risk_by_day": [round(x, 3) for x in r.risk], "levels": r.levels,
                                      "truth_cr_0800": [round(x, 3) for x in r.truth_cr],
                                      "truth_stage": r.truth_stage, "twin_cr_0800": [round(x, 3) for x in r.twin_cr]}
        if r.whatif:
            numbers["scenarios"][name]["whatif_on_day"] = WHATIF_DAY[name]
            numbers["scenarios"][name]["whatif_72h_risk"] = r.whatif
    nm = dict(sc["S6_cyp2c9"])
    nm["person"] = {**nm["person"], "cyp2c9": "*1/*1"}
    r_nm = replay("S6_cyp2c9_normal", nm)
    numbers["scenarios"]["S6_cyp2c9"]["normal_metaboliser_max_risk"] = round(max(r_nm.risk), 3)
    (DATA_DIR / "synthetic").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "synthetic" / "demo_patients.json").write_text(json.dumps(demo, indent=2), encoding="utf-8")
    (REPORTS_DIR / "demo_numbers.json").write_text(json.dumps(numbers, indent=2), encoding="utf-8")
    for name, v in numbers["scenarios"].items():
        print(name, v["summary"], v.get("whatif_72h_risk", ""), v.get("normal_metaboliser_max_risk", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
