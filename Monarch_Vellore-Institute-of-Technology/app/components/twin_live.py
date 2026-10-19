"""Live twin for the fictional personas: replay up to a chosen day (cached), then run what-if levers and the slow clock
on that twin. The replay is deterministic (seeded), so Riya's lever table on her red day reproduces
reports/demo_numbers.json exactly (tests/test_whatif.py)."""
from __future__ import annotations

import streamlit as st

from vrikka.config import load_yaml
from vrikka.physiology.renal import gfr_now
from vrikka.twin.replay import replay
from vrikka.whatif.levers import PatientContext


@st.cache_resource(show_spinner="Replaying the twin up to that day ...", max_entries=24)
def replay_ctx(pid: str, day: int):
    cfg = load_yaml("scenarios")[pid]
    return replay(pid, cfg, capture_day=day)


def patient_context(pid: str, active_events: list[str]) -> PatientContext:
    cfg = load_yaml("scenarios")[pid]
    p, h = cfg["person"], cfg.get("history", {})
    ev = cfg.get("events", {})
    pain = {ev["nsaid"]["brand"]: ev["nsaid"]["per_day"]} if "nsaid" in ev and "nsaid" in active_events else {}
    routine = load_yaml("cohort")["occupation_routine"][p["occupation"]]
    return PatientContext(generics=cfg.get("generics", []), age=p["age"], weight_kg=p["weight_kg"], egfr=p["egfr"],
                          painkiller=pain, heart_failure=bool(h.get("heart_failure")),
                          last_potassium=h.get("last_potassium"), outdoor_hours=routine["outdoor_hours"])


def active_events(pid: str, day: int) -> list[str]:
    import inspect

    lead_in = inspect.signature(replay).parameters["lead_in"].default
    off = day - lead_in + 1
    ev = load_yaml("scenarios")[pid].get("events", {})
    return sorted(k for k, v in ev.items() if v["days"][0] <= off < v["days"][1])


def twin_state(twin) -> dict:
    """Posterior means in plain units: water deficits, creatinine vs baseline, sweat multiplier, modelled filtration."""
    p = twin.p
    eff = twin.eff or {}
    gfr = gfr_now(p, max(float(twin.x[1]), 0.0), eff.get("nsaid", 0.0), eff.get("ras", 0.0)) * (
        1 - p.k_ex * eff.get("ex", 0.0))
    return {"v_tot_l": float(twin.x[0]), "v_ecf_l": float(twin.x[1]), "cr_mg_dl": float(twin.x[2]),
            "cr_ratio": float(twin.x[2]) / p.cr_base, "theta": twin.theta, "gfr_frac": gfr / p.gfr_base}
