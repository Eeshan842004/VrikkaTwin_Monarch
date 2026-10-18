"""Patient directory for the demo app (Part 6): who exists and what each record holds. Two sources, both synthetic:

1. The six FICTIONAL personas (config/scenarios.yaml) with their twin replay (reports/demo_numbers.json) and slow-clock
   ranges (reports/slowclock_demo.json). Their risk is the twin's 72-hour simulation (share of 200 Monte-Carlo runs
   meeting the KDIGO rule) shown with the display bands of config/alert_policy.yaml; the what-if levers act on it.
2. The triage panel (reports/demo_triage_panel.json, made by scripts/make_triage_panel.py): synthetic test-season
   patients scored by the FROZEN hybrid model M with the frozen Part 4 thresholds and its top-3 reasons.

Every number comes from those report files. Names are encrypted at rest (Fernet) and decrypted only for roles allowed
to see them (security/rbac.py).
"""
from __future__ import annotations

import inspect
import json
from functools import lru_cache

from vrikka.config import DATA_DIR, REPORTS_DIR, load_yaml, param
from vrikka.fastclock.display import risk_text
from vrikka.physiology.equations import creatinine_from_egfr
from vrikka.security.crypto import encrypt_text


def _json(name: str) -> dict:
    p = REPORTS_DIR / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def persona_today(s: dict) -> int:
    """Default 'today' for a persona: the first red day, else the day of highest risk."""
    lv = s["levels"]
    return lv.index("red") if "red" in lv else max(range(len(s["risk_by_day"])), key=lambda i: s["risk_by_day"][i])


def _active(ev: dict, day_offset: int) -> set[str]:
    on = set()
    for k, v in ev.items():
        a, b = v["days"]
        if a <= day_offset < b:
            on.add(k)
    return on


@lru_cache(maxsize=1)
def personas() -> dict[str, dict]:
    sc = load_yaml("scenarios")
    nums = _json("demo_numbers.json").get("scenarios", {})
    slow = _json("slowclock_demo.json").get("personas", {})
    cities = load_yaml("cities")
    from vrikka.twin.replay import replay

    lead_in = inspect.signature(replay).parameters["lead_in"].default      # replay starts this many days early
    draws = int(param("mc_draws_ui"))                                       # demo_numbers.json used these draws
    demo_p = DATA_DIR / "synthetic" / "demo_patients.json"
    dates = json.loads(demo_p.read_text(encoding="utf-8")) if demo_p.exists() else {}
    out = {}
    for pid, cfg in sc.items():
        if pid not in nums:
            continue
        p, h, s = cfg["person"], cfg.get("history", {}), nums[pid]
        today = persona_today(s)
        events = cfg.get("events", {})
        active = _active(events, today - lead_in + 1)
        chronic = cfg.get("chronic", {})
        drivers = []
        if "fever" in active:
            drivers.append("reason.rep_fever_c")
        if "gi" in active:
            drivers.append("reason.rep_gi_episodes")
        if "nsaid" in active:
            drivers.append("reason.triple_today" if chronic.get("ras") and chronic.get("diuretic")
                           else "reason.nsaid_today")
        if chronic.get("diuretic") and "nsaid" not in active:
            drivers.append("reason.on_diuretic")
        if "ors" in active:
            drivers.append("reason.rep_ors_l")
        drivers.append("reason.fc_tmax_72h")
        name = cfg.get("name") or cfg["label"].split(" (fictional)")[0].split(",")[0]
        out[pid] = {
            "patient_id": pid, "source": "persona", "fictional": True,
            "name_enc": encrypt_text(name), "label": cfg["label"], "age": p["age"], "female": p["female"],
            "city": p["city"], "language": cities[p["city"]]["default_language"], "occupation": p["occupation"],
            "generics": cfg.get("generics", []), "dm": bool(h.get("dm")), "heart_failure": bool(h.get("heart_failure")),
            "last_potassium": h.get("last_potassium"), "uacr_mg_g": h.get("uacr_mg_g"), "egfr_baseline": p["egfr"],
            "cr_baseline": creatinine_from_egfr(p["egfr"], p["age"], p["female"]), "tier": "T1",
            "dates": dates.get(pid, {}).get("dates", []), "today": today, "risk_by_day": s["risk_by_day"],
            "levels_by_day": s["levels"], "twin_cr_0800": s["twin_cr_0800"], "truth_cr_0800": s["truth_cr_0800"],
            "truth_stage": s["truth_stage"], "summary": s["summary"], "whatif_reported": s.get("whatif_72h_risk"),
            "risk": s["risk_by_day"][today], "level": s["levels"][today],
            "risk_text": risk_text(s["risk_by_day"][today], draws)["text"],
            "risk_basis": "twin_simulation", "reasons": drivers[:3],
            "slow_clock": slow.get(pid), "kfre": (slow.get(pid) or {}).get("kfre"),
            "advice_keys": [f"level.{s['levels'][today]}", f"action.{s['levels'][today]}"],
            "events_active": sorted(active), "chronic": chronic, "cyp2c9": p.get("cyp2c9"),
        }
    return out


@lru_cache(maxsize=1)
def panel() -> dict[str, dict]:
    data = _json("demo_triage_panel.json")
    out = {}
    for r in data.get("patients", []):
        rec = dict(r)
        rec["source"], rec["fictional"], rec["risk_basis"] = "panel", True, "model_M"
        rec["name_enc"] = encrypt_text(f"Synthetic patient {r['patient_id']}")
        rec["advice_keys"] = [f"level.{r['level']}", f"action.{r['level']}"]
        out[r["patient_id"]] = rec
    return out


def panel_meta() -> dict:
    return {k: v for k, v in _json("demo_triage_panel.json").items() if k != "patients"}


def all_patients() -> dict[str, dict]:
    return {**personas(), **panel()}
