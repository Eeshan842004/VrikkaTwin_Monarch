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
- Intake is split (Decisions v2 B2): plain water refills the ECF in proportion to v_ecf/v_tot; ORS / electrolyte
  drink refills ``ors_ecf_frac`` (0.9) of its volume into the ECF.
- Haemoconcentration (Decisions v5 C1): creatinine MASS is conserved when body water falls, Vd(t) = max(TBW - v_tot,
  vd_floor_frac x TBW) x 10 dL, so the concentration rises as water is lost. (Shrinking Vd inside the old ODE has no
  concentration effect at all; the mass-conserving form does.) With v_tot = 0 the result equals the old engine exactly.
- Exertion (Decisions v4 2b, v5 C2): GFR is multiplied by (1 - k_ex x ex), where ex is the lagged exertion fraction
  clip((met - ex_met_threshold) / ex_met_span, 0, 1). Only when met exceeds the threshold, so home-based people are
  unaffected.

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
    ors_ecf_frac: float = field(default_factory=lambda: param("ors_ecf_frac"))
    k_ex: float = field(default_factory=lambda: param("k_ex"))
    tau_ex_h: float = field(default_factory=lambda: param("tau_ex_h"))
    ex_met_threshold: float = field(default_factory=lambda: param("ex_met_threshold"))
    ex_met_span: float = field(default_factory=lambda: param("ex_met_span"))
    vd_floor_frac: float = field(default_factory=lambda: param("vd_floor_frac"))
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


def distribution_volume_dl(tbw_l, v_tot_l, floor_frac: float | None = None):
    """Creatinine distribution volume (dL) = current total body water x 10, floored at ``floor_frac`` x baseline TBW
    (Decisions v5 C1). Works on scalars and numpy arrays."""
    f = param("vd_floor_frac") if floor_frac is None else floor_frac
    return np.maximum(tbw_l - v_tot_l, f * tbw_l) * 10.0


def exertion_target(met, threshold: float | None = None, span: float | None = None):
    """Exertion fraction in [0, 1] for a metabolic rate: 0 at or below ``threshold``, 1 at threshold + span."""
    thr = param("ex_met_threshold") if threshold is None else threshold
    spn = param("ex_met_span") if span is None else span
    return np.clip((np.asarray(met, dtype=float) - thr) / spn, 0.0, 1.0)


def exertion_update(ex_prev: float, met: float, p: Params, dt_h: float = 1.0) -> float:
    """First-order on/off lag of the exertion fraction over ``dt_h`` hours (``tau_ex_h``)."""
    k = math.exp(-dt_h / p.tau_ex_h)
    return ex_prev * k + (1.0 - k) * float(exertion_target(met, p.ex_met_threshold, p.ex_met_span))


def creatinine_step(cr: float, gen_mg_min: float, gfr_ml_min: float, vd_dl: float, dt_h: float = 1.0,
                    vd_end_dl: float | None = None) -> float:
    """Creatinine kinetics Vd x dCr/dt = G - GFR x Cr / 100, solved exactly for constant G and GFR over dt.

    This is the single creatinine-kinetics function: the twin, the simulators and the real-data check R1b all
    import it (Decisions v1 item 14).

    Mass-conserving haemoconcentration (Decisions v5 C1): if the distribution volume changes from ``vd_dl`` to
    ``vd_end_dl`` over the step, creatinine MASS is conserved, i.e. dCr/dt = (G - GFR x Cr/100)/Vd - Cr x (dVd/dt)/Vd.
    The clearance term uses the mean volume of the step (exact for a constant Vd, second-order otherwise), and the
    concentration is rescaled by the volume ratios, so a constant volume gives exactly the old result.
    """
    vd_end = vd_dl if vd_end_dl is None else vd_end_dl
    vd_mid = 0.5 * (vd_dl + vd_end)
    cr = cr * (vd_dl / vd_mid)                          # concentration if the volume were already vd_mid
    k = 0.6 * gfr_ml_min / vd_mid                       # 1/h  (60 min/h x GFR / (100 x Vd))
    if k < 1e-12:
        cr_n = cr + 60.0 * gen_mg_min / vd_mid * dt_h
    else:
        css = 100.0 * gen_mg_min / gfr_ml_min
        cr_n = css + (cr - css) * math.exp(-k * dt_h)
    return cr_n * (vd_mid / vd_end)                     # then the volume moves on to vd_end


def step_hour(p: Params, s: dict, sweat_l_h: float, gi_loss_l_h: float, intake_l_h: float, eff: dict,
              fever_excess_c: float = 0.0, phi_mult: float = 1.0, ors_l_h: float = 0.0, ex: float = 0.0) -> dict:
    """Advance one hour. ``s`` = {'v_tot','v_ecf','cr'}; ``eff`` = lagged drug effect levels by channel.

    ``intake_l_h`` is extra plain water (beyond the habitual drinking already in ``phi_drink``); ``ors_l_h`` is
    ORS / electrolyte drink; ``ex`` is the lagged exertion fraction for this hour (0 = rest).
    """
    sweat_net = (sweat_l_h * p.theta_sweat * (1.0 - p.phi_drink * phi_mult)
                 + p.fever_loss_l_day_per_c * max(fever_excess_c, 0.0) / 24.0)
    drug = (p.diuretic_loss_l_day * eff["diuretic"] + p.sglt2_loss_l_day * eff["sglt2"]) / 24.0
    tot_loss = sweat_net + gi_loss_l_h + drug
    ecf_loss = sweat_net * p.ecf_frac_sweat + gi_loss_l_h * p.ecf_frac_gi + drug * p.ecf_frac_drug
    v_tot, v_ecf = s["v_tot"], s["v_ecf"]
    intake_ecf = intake_l_h * (v_ecf / v_tot if v_tot > 1e-6 else 1.0) + ors_l_h * p.ors_ecf_frac
    v_tot_n = max(v_tot + tot_loss - intake_l_h - ors_l_h - v_tot / p.tau_recover_h, 0.0)
    v_ecf_n = min(max(v_ecf + ecf_loss - intake_ecf - v_ecf / p.tau_recover_h, 0.0), v_tot_n)
    gfr = gfr_now(p, v_ecf_n, eff["nsaid"], eff["ras"]) * (1.0 - p.k_ex * ex)
    vd0 = float(distribution_volume_dl(p.tbw_l, v_tot, p.vd_floor_frac))
    vd1 = float(distribution_volume_dl(p.tbw_l, v_tot_n, p.vd_floor_frac))
    cr = creatinine_step(s["cr"], p.cr_generation_mg_min, gfr, vd0, 1.0, vd1)
    return {"v_tot": v_tot_n, "v_ecf": v_ecf_n, "cr": cr, "gfr": gfr}


INPUT_DEFAULTS = {"sweat_l_h": 0.0, "gi_loss_l_h": 0.0, "intake_l_h": 0.0, "ors_l_h": 0.0, "fever_excess_c": 0.0,
                  "phi_mult": 1.0, "met": 0.0,
                  "nsaid": 0.0, "ras": 0.0, "diuretic": 0.0, "mra": 0.0, "sglt2": 0.0}


def simulate(p: Params, inputs: dict, s0: dict | None = None, eff0: dict | None = None) -> dict[str, np.ndarray]:
    """Run hour by hour. ``inputs`` maps names in INPUT_DEFAULTS to length-T arrays (missing -> default).

    Drug inputs are target effect levels: NSAID in genotype-adjusted normalised units, other drugs 0/1. Chronic
    drugs start at steady state (``eff0`` defaults to each drug's first-hour level). ``met`` (metabolic rate, met
    units) drives the exertional GFR fall; the lagged exertion fraction starts at ``eff0['ex']`` (default 0 = rest).
    """
    T = len(next(iter(inputs.values())))
    x = {k: np.broadcast_to(np.asarray(inputs.get(k, v), dtype=float), (T,)) for k, v in INPUT_DEFAULTS.items()}
    s = dict(s0 or {"v_tot": 0.0, "v_ecf": 0.0, "cr": p.cr_base})
    eff = dict(eff0 or {ch: float(x[ch][0]) for ch in CHANNELS})
    ex = float(eff.pop("ex", 0.0))
    out = {k: np.empty(T) for k in ("v_tot", "v_ecf", "cr", "gfr", "ex", *(f"eff_{c}" for c in CHANNELS))}
    for t in range(T):
        for ch in CHANNELS:
            eff[ch] = drug_effect(eff[ch], float(x[ch][t]), p.half_life_h[ch])
        ex = exertion_update(ex, float(x["met"][t]), p)
        s = step_hour(p, s, float(x["sweat_l_h"][t]), float(x["gi_loss_l_h"][t]), float(x["intake_l_h"][t]), eff,
                      float(x["fever_excess_c"][t]), float(x["phi_mult"][t]), float(x["ors_l_h"][t]), ex)
        out["ex"][t] = ex
        for k in ("v_tot", "v_ecf", "cr", "gfr"):
            out[k][t] = s[k]
        for ch in CHANNELS:
            out[f"eff_{ch}"][t] = eff[ch]
    return out
