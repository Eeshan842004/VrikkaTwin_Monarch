"""What-if levers on the personal twin (master plan §14; Decisions v1 item 1; STATUS Part 5).

Each lever changes the twin's 72-hour inputs and the Monte-Carlo risk is recomputed with the SAME random draws
(common random numbers), so differences between rows come from the lever, not from simulation noise.
Order (config/whatif.yaml): (1) painkiller swap NSAID -> paracetamol, (2) ORS / fluids and the work-hour shift,
(3) drug pauses last, each with the badge "individualised, weak evidence (Think Kidneys 2018), clinician decides".

Guardrails decide whether a lever is offered (whatif/guardrails.py): ORS is withheld with heart failure, eGFR < 30 or
K >= 5.5; the paracetamol total is checked against the ceiling; heart failure + a diuretic pause carries a warning;
K >= 5.5 adds a caution to every lever. Drug classes in drugs_india.yaml ``never_levers`` are never offered.
Patient-facing text never says "stop your medicine": pauses are "ask your doctor whether to pause ...".
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from vrikka.config import SEED, load_yaml, param
from vrikka.fastclock.display import risk_text
from vrikka.whatif import guardrails as gr

SweatFn = Callable[[int], tuple[np.ndarray, np.ndarray]]     # work start hour -> (sweat_l_h, met) over 72 h


@dataclass
class PatientContext:
    generics: list[str]                                   # chronic medicines, generic names
    age: float
    weight_kg: float
    egfr: float
    painkiller: dict[str, float] = field(default_factory=dict)   # brand -> tablets per day taken now
    heart_failure: bool = False
    last_potassium: float | None = None
    liver_disease: bool = False
    alcohol_use: bool = False
    outdoor_hours: float = 0.0

    @property
    def classes(self) -> set[str]:
        brands = load_yaml("drugs_india")["brands"]
        cls = gr.drug_classes(self.generics)
        for b in self.painkiller:
            c = brands[b.lower()]["class"]
            cls |= set(c if isinstance(c, list) else [c])
        return cls


def config() -> dict:
    return load_yaml("whatif")


def _pause_reason_key(classes: list[str]) -> str:
    return f"pause_reason.{classes[0]}"


def swapped_tablets(ctx: PatientContext) -> dict[str, float]:
    """Painkiller tablets after the swap: every NSAID-containing brand is replaced tablet-for-tablet by paracetamol."""
    brands = load_yaml("drugs_india")["brands"]
    to = config()["levers"]["painkiller_swap"]["swap_to_brand"]
    out: dict[str, float] = {}
    for b, n in ctx.painkiller.items():
        cls = brands[b.lower()]["class"]
        has_nsaid = bool({"nsaid_cyp2c9", "nsaid_other"} & set(cls if isinstance(cls, list) else [cls]))
        key = to if has_nsaid else b.lower()
        out[key] = out.get(key, 0.0) + n
    return out


def available_levers(ctx: PatientContext) -> list[dict]:
    """The levers that apply to this patient, in the fixed order, with guardrail status and badges."""
    cfg = config()
    never = set(load_yaml("drugs_india")["never_levers"])
    cls = ctx.classes
    k = gr.potassium_rule(ctx.last_potassium)
    out = []
    for name in cfg["order"]:
        lv = cfg["levers"][name]
        need = set(lv.get("applies_if_classes", []))
        assert not need & never, f"{name} would pause a never-lever class"
        if need and not need & cls:
            continue
        if name == "work_shift" and ctx.outdoor_hours < lv["applies_if_outdoor_hours_at_least"]:
            continue
        row = {"name": name, "group": lv["group"], "label_key": lv["label_key"], "allowed": True,
               "blocked_reason_keys": [], "badge_key": None, "warning_keys": [], "reason_key": None, "detail": {}}
        if name == "ors":
            g = gr.ors_guardrail(ctx.heart_failure, ctx.egfr, ctx.last_potassium)
            row["allowed"], row["blocked_reason_keys"] = g["ors_lever_allowed"], g["reason_keys"]
            row["badge_key"] = g["badge_key"]
            row["detail"]["ors_l_day"] = param("whatif_ors_l_day")
        elif name == "painkiller_swap":
            chk = gr.paracetamol_check(swapped_tablets(ctx), ctx.age, ctx.weight_kg, ctx.liver_disease,
                                       ctx.alcohol_use)
            row["detail"] = {"paracetamol": chk, "tablets_after": swapped_tablets(ctx)}
            if not chk["within_ceiling"]:
                row["warning_keys"].append(chk["message_key"])
        elif name == "work_shift":
            row["detail"]["start_hour"] = int(param("whatif_work_start_hour"))
        elif lv["group"] == 3:
            row["badge_key"] = cfg["pause_badge_key"]
            present = sorted(need & cls)
            row["reason_key"] = _pause_reason_key(present)
            row["warning_keys"] += gr.pause_warnings(present, ctx.heart_failure)
        if k["caution_on_levers"]:
            row["warning_keys"].append(k["message_key"])
        out.append(row)
    return out


def apply_lever(name: str, future: dict, sweat_fn: SweatFn | None = None) -> dict:
    """New 72-hour input dict with one lever applied (inputs as for ``twin.risk_mc.aki_risk_72h``)."""
    cfg = config()["levers"][name]
    f = dict(future)
    if name == "painkiller_swap":
        f["nsaid"] = 0.0
    elif name == "ors":
        f["ors_l_h"] = np.asarray(f.get("ors_l_h", 0.0), dtype=float) + param("whatif_ors_l_day") / 24.0
    elif name == "work_shift":
        if sweat_fn is None:
            raise ValueError("the work-hour shift needs the forecast weather (sweat_fn)")
        f["sweat_l_h"], f["met"] = sweat_fn(int(param("whatif_work_start_hour")))
    elif cfg.get("channel"):
        f[cfg["channel"]] = 0.0
    return f


def run_levers(twin, future: dict, baseline_cr: float, ctx: PatientContext, selected: list[str] | None = None,
               n_draws: int | None = None, seed: int = SEED, sweat_fn: SweatFn | None = None) -> list[dict]:
    """Cumulative what-if table: "continue as is", then each selected, allowed lever added in the fixed order.

    Every row has the 72-h risk, its display text (with the 95 % Monte-Carlo interval, never "0%"), and the lever's
    guardrail status, badge and warnings. Blocked levers are listed with their reasons but not applied.
    """
    from vrikka.twin.risk_mc import aki_risk_72h

    n = int(n_draws or param("mc_draws_ui"))
    levers = available_levers(ctx)
    if selected is not None:
        levers = [lv for lv in levers if lv["name"] in selected]
    p0 = aki_risk_72h(twin, future, baseline_cr, n, seed=seed)
    rows = [{"name": "continue", "label_key": "lever.continue", "applied": [], "risk": p0, **risk_text(p0, n)}]
    cur, applied = dict(future), []
    for lv in levers:
        if not lv["allowed"] or (lv["name"] == "work_shift" and sweat_fn is None):
            rows.append({**lv, "applied": list(applied), "risk": None, "text": None, "skipped": True})
            continue
        cur = apply_lever(lv["name"], cur, sweat_fn)
        applied.append(lv["name"])
        p = aki_risk_72h(twin, cur, baseline_cr, n, seed=seed)
        rows.append({**lv, "applied": list(applied), "risk": p, **risk_text(p, n)})
    return rows
