"""Ground-truth physiology for the synthetic cohort (master plan §11.1). Simulator only; the predictor never imports it.

Two regimes:
- ``mismatched`` (headline): a deliberately DIFFERENT kidney model from the twin's. GFR depends on renal perfusion
  pressure: MAP = MAP_base - k_map x ECF deficit; below a personal lower autoregulation limit (LLA, higher with age,
  hypertension and CKD) GFR falls with pressure. NSAIDs raise the LLA (lost prostaglandin dilation); ACEi/ARB remove
  the efferent back-up, so GFR falls further once pressure is below the LLA. Per-patient parameters come from wider
  spreads than the twin's priors, and there are causes the twin cannot see: sepsis-like AKI, exertional muscle
  breakdown (raises creatinine generation) and co-trimoxazole (blocks creatinine secretion).
- ``matched`` (optimistic ceiling): the twin's own equations (``physiology.batch``) with each patient's true sweat
  multiplier and drinking fraction, and no hidden causes.

The water balance (sweat, drinking, fever/GI/diuretic losses, renal conservation) has the same structure in both,
with the patient's true parameters. Creatinine kinetics use the shared exact solution (a physical law, not a choice),
with mass-conserving haemoconcentration (Decisions v5 C1). Both regimes also include the exertional GFR fall
(Decisions v4 2b / v5 C2): the mismatched world gives each patient hidden ``true_k_ex`` / ``true_tau_ex_h`` (spread
around the registry values); the matched regime uses the registry values. The truth-only muscle term is the episodic
``rhabdo`` generation multiplier of heavy workers (a routine muscle-release term is deliberately NOT added).
Outputs are one value per day at 08:00 (Decisions v1 item 5), plus daily maxima for diagnostics.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from vrikka.config import param
from vrikka.physiology.batch import creatinine_step_vec, exertion_update_vec, stack_params, step_hour_vec
from vrikka.physiology.renal import CHANNELS, Params, distribution_volume_dl

MISMATCH = {  # constants of the mismatched kidney model ([A]; documented in PROGRESS.md)
    # LLA rise at full prostaglandin inhibition. Calibrated once to calibration target L1 (triple vs double therapy
    # within antihypertensive users, pass band 1.1-2.5, literature ~1.8 for new combinations): 18 mmHg gave RR 4.46
    # (outside the band), 6 mmHg gives 1.76. Not fitted further (PROGRESS.md, Part 3).
    "nsaid_lla_shift_mmhg": 6.0,
    "map_floor_mmhg": 45.0,  # GFR ~0 at this MAP
    "ras_efferent_loss": 0.5,  # extra fractional GFR loss below the LLA on full ACEi/ARB effect
    "sepsis_gfr_mult": (0.35, 0.6),
    "rhabdo_generation_mult": (1.5, 2.0),
    "cotrim_generation_mult": 1.15,
}


def pressure_gfr_fraction(v_ecf, map_base, k_map, lla_eff, ras_eff=0.0):
    """The mismatched world's kidney model: GFR as a fraction of baseline from renal perfusion pressure.

    MAP = MAP_base - k_map x ECF deficit; at or above the (effective) lower autoregulation limit GFR is untouched,
    below it GFR falls linearly to ~0 at ``map_floor_mmhg``; ACEi/ARB remove the efferent back-up below the limit.
    """
    mapp = map_base - k_map * v_ecf
    floor = MISMATCH["map_floor_mmhg"]
    f_press = np.where(mapp >= lla_eff, 1.0, np.clip((mapp - floor) / (lla_eff - floor), 0.0, 1.0))
    return f_press * (1 - MISMATCH["ras_efferent_loss"] * ras_eff * (1 - f_press))


def diuretic_name(value) -> str | None:
    """Generic diuretic name, or None (pandas stores 'no diuretic' as NaN)."""
    return value if isinstance(value, str) and value else None


def _params(people: pd.DataFrame, true: bool) -> list[Params]:
    out = []
    for r in people.itertuples(index=False):
        p = Params.from_patient(
            age=r.age,
            female=r.female,
            weight_kg=r.weight_kg,
            egfr=r.egfr_baseline,
            height_m=r.height_m,
            cr_base=r.cr_baseline,
            diuretic=diuretic_name(r.diuretic),
            water_at_work=r.water_access_at_work,
        )
        if true:
            p.theta_sweat, p.phi_drink = r.true_theta_sweat, r.true_phi_drink
        out.append(p)
    return out


def drug_targets(people: pd.DataFrame, ev: dict, d: int) -> dict[str, np.ndarray]:
    adh = ev["adherent"][d]
    return {
        "nsaid": ev["nsaid_units"][d],
        "ras": (people["on_ras"].to_numpy() & adh).astype(float),
        "diuretic": (people["diuretic"].map(diuretic_name).notna().to_numpy() & adh).astype(float),
        "mra": (people["on_mra"].to_numpy() & adh).astype(float),
        "sglt2": (people["on_sglt2i"].to_numpy() & adh).astype(float),
    }


def simulate_truth(
    people: pd.DataFrame,
    sweat: np.ndarray,
    ev: dict,
    regime: str = "mismatched",
    seed: int = 42,
    met: np.ndarray | None = None,
    record_hours: tuple[int, ...] = (),
) -> dict[str, np.ndarray]:
    """Hour-by-hour truth for all patients. ``sweat`` (T, N) L/h; ``met`` (T, N) metabolic rate (None = rest);
    ``ev`` daily event arrays (D, N).

    Returns daily arrays (D, N): cr_0800, v_tot_0800, v_ecf_0800, gfr_frac_0800, cr_max, gfr_frac_min. With
    ``record_hours`` (absolute hour indices) it also returns ``cr_at`` (len(record_hours), N): creatinine after
    processing each of those hours (the state at the END of that hour; 08:00 of day d is hour 24 d + 7).
    """
    rng = np.random.default_rng(seed)
    T, N = sweat.shape
    D = T // 24
    P = stack_params(_params(people, true=True))
    if regime == "mismatched":
        P["tau_recover_h"] = people["true_tau_recover_h"].to_numpy(dtype=float)
        P["ecf_frac_sweat"] = people["true_ecf_frac_sweat"].to_numpy(dtype=float)
        P["diuretic_loss_l_day"] = P["diuretic_loss_l_day"] * people["true_diuretic_loss_mult"].to_numpy(dtype=float)
        map_base = ((people["sbp_base"] + 2 * people["dbp_base"]) / 3).to_numpy(dtype=float)
        k_map = people["true_k_map"].to_numpy(dtype=float)
        lla = people["true_lla"].to_numpy(dtype=float)
        P["k_ex"] = people["true_k_ex"].to_numpy(dtype=float)
        P["tau_ex_h"] = people["true_tau_ex_h"].to_numpy(dtype=float)
        sepsis_mult = rng.uniform(*MISMATCH["sepsis_gfr_mult"], N)
        rhabdo_mult = rng.uniform(*MISMATCH["rhabdo_generation_mult"], N)
    elif regime != "matched":
        raise ValueError(regime)
    gen0 = P["gfr_base"] * P["cr_base"] / 100.0
    lag = {ch: np.exp(-math.log(2.0) / P[f"half_life_{ch}"]) for ch in CHANNELS}

    v_tot, v_ecf, cr = np.zeros(N), np.zeros(N), P["cr_base"].copy()
    ex = np.zeros(N)
    eff = drug_targets(people, ev, 0)
    out = {k: np.empty((D, N)) for k in ("cr_0800", "v_tot_0800", "v_ecf_0800", "gfr_frac_0800")}
    cr_max, gfr_min = np.full((D, N), -np.inf), np.full((D, N), np.inf)
    rec = {h: i for i, h in enumerate(record_hours)}
    cr_at = np.full((len(record_hours), N), np.nan)
    poor_mult = param("poor_intake_mult")
    for t in range(T):
        d = t // 24
        tgt = drug_targets(people, ev, d)
        for ch in CHANNELS:
            eff[ch] = eff[ch] * lag[ch] + (1 - lag[ch]) * tgt[ch]
        gi = (
            ev["vomit_episodes"][d] * param("vomit_loss_l") + ev["diarrhoea_episodes"][d] * param("diarrhoea_loss_l")
        ) / 24
        phi_mult = np.where(ev["poor_intake"][d], poor_mult, 1.0)
        ors = ev["ors_l_day"][d] / 24
        if met is not None:
            ex = exertion_update_vec(ex, met[t], P)
        if regime == "matched":
            v_tot, v_ecf, cr, gfr = step_hour_vec(
                P, v_tot, v_ecf, cr, eff, sweat[t], gi, 0.0, ev["fever_excess_c"][d], phi_mult, ors, ex
            )
        else:
            # --- same water balance structure, true parameters ---
            sweat_net = (
                sweat[t] * P["theta_sweat"] * (1 - P["phi_drink"] * phi_mult)
                + P["fever_loss_l_day_per_c"] * ev["fever_excess_c"][d] / 24.0
            )
            drug = P["diuretic_loss_l_day"] * eff["diuretic"] / 24.0
            ecf_loss = sweat_net * P["ecf_frac_sweat"] + gi * P["ecf_frac_gi"] + drug * P["ecf_frac_drug"]
            intake_ecf = ors * P["ors_ecf_frac"]
            v_tot_prev = v_tot
            v_tot = np.maximum(v_tot + sweat_net + gi + drug - ors - v_tot / P["tau_recover_h"], 0.0)
            v_ecf = np.minimum(np.maximum(v_ecf + ecf_loss - intake_ecf - v_ecf / P["tau_recover_h"], 0.0), v_tot)
            # --- different kidney model: pressure autoregulation ---
            i_pg = eff["nsaid"] / (eff["nsaid"] + P["nsaid_e50"])
            lla_eff = lla + MISMATCH["nsaid_lla_shift_mmhg"] * i_pg
            f = pressure_gfr_fraction(v_ecf, map_base, k_map, lla_eff, eff["ras"])
            f = f * np.where(ev["sepsis_like"][d], sepsis_mult, 1.0)
            gfr = P["gfr_base"] * f * (1.0 - P["k_ex"] * ex)
            gen = (
                gen0
                * np.where(ev["rhabdo"][d], rhabdo_mult, 1.0)
                * np.where(ev["cotrimoxazole"][d], MISMATCH["cotrim_generation_mult"], 1.0)
            )
            cr = creatinine_step_vec(
                cr,
                gen,
                gfr,
                distribution_volume_dl(P["tbw_l"], v_tot_prev, P["vd_floor_frac"]),
                distribution_volume_dl(P["tbw_l"], v_tot, P["vd_floor_frac"]),
            )
        cr_max[d] = np.maximum(cr_max[d], cr)
        gfr_min[d] = np.minimum(gfr_min[d], gfr / P["gfr_base"])
        if t in rec:
            cr_at[rec[t]] = cr
        if (t + 1) % 24 == 8:  # state after this hour is the 08:00 value of day d
            out["cr_0800"][d], out["v_tot_0800"][d], out["v_ecf_0800"][d] = cr, v_tot, v_ecf
            out["gfr_frac_0800"][d] = gfr / P["gfr_base"]
    out["cr_max"], out["gfr_frac_min"] = cr_max, gfr_min
    if record_hours:
        out["cr_at"] = cr_at
    return out
