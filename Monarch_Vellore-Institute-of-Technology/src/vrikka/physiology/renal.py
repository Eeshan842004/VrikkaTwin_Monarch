"""Two-deficit volume model, lagged drug effects, autoregulation and creatinine kinetics (master plan §9.1, §9.4).

Chain: unreplaced sweat + fever/GI/diuretic losses - intake - renal conservation -> total-water deficit ``v_tot``
(seen by the morning weight) and extracellular deficit ``v_ecf`` (drives GFR; hypotonic sweat counts x0.5) ->
GFR = GFR_base x [1 - h(d) x (1 - protection)] -> creatinine kinetics.

- ``h(d) = d^n / (d^n + d50^n)``, d = v_ecf / (ecv_frac x weight): fraction of filtration lost when unprotected.
- protection = a_tot x [s x (1 - I_PG(NSAID)) + (1 - s) x (1 - I_RAS x RAS_eff)]: NSAIDs remove the afferent
  (prostaglandin) arm, ACEi/ARB remove the efferent (angiotensin II) arm, diuretics raise d.
- Drug effects switch on and off with a first-order lag; each drug has its own effect half-life from the registry
  (Decisions v1 item 4). There is no shared "diuretic" constant.
- Fever is always degrees **above 37 degC**.
- SGLT2 inhibitors have no AKI-raising volume effect by default (``sglt2_loss_l_day`` = 0; Decisions v1 item 3).

Every constant comes from config/parameters.yaml. Units: G in mg/min, GFR in mL/min, Cr in mg/dL, Vd in dL.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

from vrikka.config import load_yaml, param
from vrikka.physiology.equations import creatinine_from_egfr

CHANNELS = ("nsaid", "ras", "diuretic", "mra", "sglt2")
DIURETIC_CLASSES = {"thiazide": "diuretic_loss_thiazide_l_day", "loop": "diuretic_loss_loop_l_day"}


def drug_lexicon() -> dict:
    return load_yaml("drugs_india")


def half_life_for(drug_or_class: str) -> float:
    """Effect half-life (h) for a generic drug or drug class, from the registry via ``half_life_key``."""
    keys = drug_lexicon()["half_life_key"]
    if drug_or_class not in keys:
        raise KeyError(f"no effect half-life registered for '{drug_or_class}' (add it to drugs_india.yaml)")
    return param(keys[drug_or_class])


def diuretic_class(generic: str) -> str:
    cls = drug_lexicon()["generics"].get(generic)
    if cls not in DIURETIC_CLASSES:
        raise ValueError(f"'{generic}' is not a thiazide-type or loop diuretic")
    return cls


def a_tot_for(age: float, egfr: float) -> float:
    """Autoregulatory protection: young value for age < 60 and eGFR >= 60, falling linearly to the old value at
    age >= 75 or eGFR < 45 (the worse of the two drives it)."""
    f = max(min(max((age - 60.0) / 15.0, 0.0), 1.0), min(max((60.0 - egfr) / 15.0, 0.0), 1.0))
    return param("a_tot_young") + f * (param("a_tot_old") - param("a_tot_young"))


@dataclass
class Params:
    """Per-patient physiology parameters. Build with :meth:`from_patient` so defaults come from the registry."""

    weight_kg: float
    female: bool
    age: float
    gfr_base: float          # mL/min (absolute)
    cr_base: float           # mg/dL
    a_tot: float
    phi_drink: float
    tau_recover_h: float
    diuretic_loss_l_day: float = 0.0
    sglt2_loss_l_day: float = field(default_factory=lambda: param("sglt2_loss_l_day"))
    theta_sweat: float = 1.0
    ecv_frac: float = field(default_factory=lambda: param("ecv_frac"))
    ecf_frac_sweat: float = field(default_factory=lambda: param("ecf_frac_sweat"))
    ecf_frac_gi: float = field(default_factory=lambda: param("ecf_frac_gi"))
    ecf_frac_drug: float = field(default_factory=lambda: param("ecf_frac_drug"))
    d50: float = field(default_factory=lambda: param("d50"))
    hill_n: float = field(default_factory=lambda: param("hill_n"))
    aff_share: float = field(default_factory=lambda: param("aff_share"))
    i_ras: float = field(default_factory=lambda: param("i_ras"))
    nsaid_e50: float = field(default_factory=lambda: param("nsaid_e50"))
    fever_loss_l_day_per_c: float = field(default_factory=lambda: param("fever_loss_l_day_per_c"))
    half_life_h: dict = field(default_factory=dict)

    @classmethod
    def from_patient(cls, *, age: float, female: bool, weight_kg: float, egfr: float, height_m: float | None = None,
                     cr_base: float | None = None, diuretic: str | None = None, water_at_work: bool = True,
                     sickle_trait: bool = False, theta_sweat: float = 1.0, **overrides) -> Params:
        """Registry-driven parameters for one person.

        ``egfr`` is the baseline eGFR (mL/min/1.73 m2). With ``height_m`` it is de-indexed to an absolute GFR via
        Mosteller BSA; without it the indexed value is used. ``diuretic`` is the generic name of the patient's
        thiazide-type or loop diuretic (sets both the daily loss and the effect half-life).
        """
        gfr = egfr * math.sqrt(height_m * 100 * weight_kg / 3600) / 1.73 if height_m else egfr
        phi = param("phi_drink_young") if age < 60 else param("phi_drink_old")
        if not water_at_work:
            phi *= param("phi_drink_no_water_at_work_mult")
        tau = param("tau_recover_h") * (param("sickle_trait_tau_mult") if sickle_trait else 1.0)
        half = {"nsaid": param("half_life_nsaid_h"), "ras": param("half_life_ras_h"),
                "mra": param("half_life_mra_h"), "sglt2": param("half_life_sglt2_h"),
                "diuretic": half_life_for(diuretic) if diuretic else param("half_life_hctz_h")}
        loss = param(DIURETIC_CLASSES[diuretic_class(diuretic)]) if diuretic else 0.0
        p = cls(weight_kg=weight_kg, female=female, age=age, gfr_base=gfr,
                cr_base=cr_base if cr_base is not None else creatinine_from_egfr(egfr, age, female),
                a_tot=a_tot_for(age, egfr), phi_drink=phi, tau_recover_h=tau, diuretic_loss_l_day=loss,
                theta_sweat=theta_sweat, half_life_h=half)
        return replace(p, **overrides) if overrides else p

    @property
    def ecv0(self) -> float:
        return self.ecv_frac * self.weight_kg

    @property
    def tbw_l(self) -> float:
        frac = param("tbw_frac_female") if self.female else param("tbw_frac_male")
        return (frac + (param("tbw_frac_young_bonus") if self.age < 60 else 0.0)) * self.weight_kg

    @property
    def cr_generation_mg_min(self) -> float:
        return self.gfr_base * self.cr_base / 100.0


def drug_effect(prev: float, on: float, t_half_h: float, dt_h: float = 1.0) -> float:
    """First-order on/off effect lag over ``dt_h`` hours (``on`` = target effect level)."""
    k = math.exp(-math.log(2.0) * dt_h / t_half_h)
    return prev * k + (1.0 - k) * on


def gfr_now(p: Params, v_ecf_l: float, nsaid_eff: float, ras_eff: float) -> float:
    """GFR (mL/min) for an ECF deficit and lagged drug effects. ``nsaid_eff`` is in genotype-adjusted units."""
    d = max(v_ecf_l, 0.0) / p.ecv0
    h = d ** p.hill_n / (d ** p.hill_n + p.d50 ** p.hill_n) if d > 0 else 0.0
    i_pg = nsaid_eff / (nsaid_eff + p.nsaid_e50) if nsaid_eff > 0 else 0.0
    prot = p.a_tot * (p.aff_share * (1.0 - i_pg) + (1.0 - p.aff_share) * (1.0 - p.i_ras * ras_eff))
    return p.gfr_base * (1.0 - h * (1.0 - prot))


def creatinine_step(cr: float, gen_mg_min: float, gfr_ml_min: float, vd_dl: float, dt_h: float = 1.0) -> float:
    """Creatinine kinetics Vd x dCr/dt = G - GFR x Cr / 100, solved exactly for constant G and GFR over dt.

    This is the single creatinine-kinetics function: the twin, the simulators and the real-data check R1b all
    import it (Decisions v1 item 14).
    """
    k = 0.6 * gfr_ml_min / vd_dl                       # 1/h  (60 min/h x GFR / (100 x Vd))
    if k < 1e-12:
        return cr + 60.0 * gen_mg_min / vd_dl * dt_h
    css = 100.0 * gen_mg_min / gfr_ml_min
    return css + (cr - css) * math.exp(-k * dt_h)


def step_hour(p: Params, s: dict, sweat_l_h: float, gi_loss_l_h: float, intake_l_h: float, eff: dict,
              fever_excess_c: float = 0.0, phi_mult: float = 1.0) -> dict:
    """Advance one hour. ``s`` = {'v_tot','v_ecf','cr'}; ``eff`` = lagged drug effect levels by channel."""
    sweat_net = (sweat_l_h * p.theta_sweat * (1.0 - p.phi_drink * phi_mult)
                 + p.fever_loss_l_day_per_c * max(fever_excess_c, 0.0) / 24.0)
    drug = (p.diuretic_loss_l_day * eff["diuretic"] + p.sglt2_loss_l_day * eff["sglt2"]) / 24.0
    tot_loss = sweat_net + gi_loss_l_h + drug
    ecf_loss = sweat_net * p.ecf_frac_sweat + gi_loss_l_h * p.ecf_frac_gi + drug * p.ecf_frac_drug
    v_tot, v_ecf = s["v_tot"], s["v_ecf"]
    intake_ecf = intake_l_h * (v_ecf / v_tot if v_tot > 1e-6 else 1.0)
    v_tot_n = max(v_tot + tot_loss - intake_l_h - v_tot / p.tau_recover_h, 0.0)
    v_ecf_n = min(max(v_ecf + ecf_loss - intake_ecf - v_ecf / p.tau_recover_h, 0.0), v_tot_n)
    gfr = gfr_now(p, v_ecf_n, eff["nsaid"], eff["ras"])
    cr = creatinine_step(s["cr"], p.cr_generation_mg_min, gfr, p.tbw_l * 10.0)
    return {"v_tot": v_tot_n, "v_ecf": v_ecf_n, "cr": cr, "gfr": gfr}


INPUT_DEFAULTS = {"sweat_l_h": 0.0, "gi_loss_l_h": 0.0, "intake_l_h": 0.0, "fever_excess_c": 0.0, "phi_mult": 1.0,
                  "nsaid": 0.0, "ras": 0.0, "diuretic": 0.0, "mra": 0.0, "sglt2": 0.0}


def simulate(p: Params, inputs: dict, s0: dict | None = None, eff0: dict | None = None) -> dict[str, np.ndarray]:
    """Run hour by hour. ``inputs`` maps names in INPUT_DEFAULTS to length-T arrays (missing -> default).

    Drug inputs are target effect levels: NSAID in genotype-adjusted normalised units, other drugs 0/1. Chronic
    drugs start at steady state (``eff0`` defaults to each drug's first-hour level).
    """
    T = len(next(iter(inputs.values())))
    x = {k: np.broadcast_to(np.asarray(inputs.get(k, v), dtype=float), (T,)) for k, v in INPUT_DEFAULTS.items()}
    s = dict(s0 or {"v_tot": 0.0, "v_ecf": 0.0, "cr": p.cr_base})
    eff = dict(eff0 or {ch: float(x[ch][0]) for ch in CHANNELS})
    out = {k: np.empty(T) for k in ("v_tot", "v_ecf", "cr", "gfr", *(f"eff_{c}" for c in CHANNELS))}
    for t in range(T):
        for ch in CHANNELS:
            eff[ch] = drug_effect(eff[ch], float(x[ch][t]), p.half_life_h[ch])
        s = step_hour(p, s, float(x["sweat_l_h"][t]), float(x["gi_loss_l_h"][t]), float(x["intake_l_h"][t]), eff,
                      float(x["fever_excess_c"][t]), float(x["phi_mult"][t]))
        for k in ("v_tot", "v_ecf", "cr", "gfr"):
            out[k][t] = s[k]
        for ch in CHANNELS:
            out[f"eff_{ch}"][t] = eff[ch]
    return out
