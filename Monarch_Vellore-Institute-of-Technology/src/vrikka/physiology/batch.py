"""Vectorised physiology: N patients or Monte-Carlo draws at once (master plan §9.5).

Same equations as :mod:`vrikka.physiology.renal` (tested to match the scalar engine to 4 decimals), written with
numpy arrays of shape (N,) so a whole cohort or a set of posterior draws advances one hour per call. Includes the
mass-conserving haemoconcentration and the exertional GFR fall (Decisions v5 C1, C2).
"""
from __future__ import annotations

import math

import numpy as np

from vrikka.physiology.renal import CHANNELS, INPUT_DEFAULTS, Params, distribution_volume_dl, exertion_target

PARAM_FIELDS = ("weight_kg", "gfr_base", "cr_base", "a_tot", "phi_drink", "tau_recover_h", "diuretic_loss_l_day",
                "sglt2_loss_l_day", "theta_sweat", "ecv_frac", "ecf_frac_sweat", "ecf_frac_gi", "ecf_frac_drug",
                "d50", "hill_n", "aff_share", "i_ras", "nsaid_e50", "fever_loss_l_day_per_c", "ors_ecf_frac",
                "k_ex", "tau_ex_h", "ex_met_threshold", "ex_met_span", "vd_floor_frac")


def stack_params(params: list[Params]) -> dict[str, np.ndarray]:
    """Turn a list of per-patient Params into a dict of (N,) arrays (plus derived TBW and half-lives)."""
    P = {f: np.array([getattr(p, f) for p in params], dtype=float) for f in PARAM_FIELDS}
    P["tbw_l"] = np.array([p.tbw_l for p in params])
    for ch in CHANNELS:
        P[f"half_life_{ch}"] = np.array([p.half_life_h[ch] for p in params])
    return P


def creatinine_step_vec(cr, gen, gfr, vd0, vd1, dt_h: float = 1.0):
    """Vector form of :func:`vrikka.physiology.renal.creatinine_step` (same mass-conserving scheme; a constant
    volume, vd0 == vd1, reproduces the old engine exactly)."""
    vd_mid = 0.5 * (vd0 + vd1)
    cr = cr * (vd0 / vd_mid)
    k = 0.6 * gfr / vd_mid
    css = np.where(gfr > 1e-9, 100.0 * gen / np.maximum(gfr, 1e-9), 0.0)
    cr_n = np.where(k > 1e-12, css + (cr - css) * np.exp(-k * dt_h), cr + 60.0 * gen / vd_mid * dt_h)
    return cr_n * (vd_mid / vd1)


def exertion_update_vec(ex, met, P: dict, dt_h: float = 1.0):
    """First-order lag of the exertion fraction (per row ``tau_ex_h``) towards clip((met - threshold) / span, 0, 1)."""
    k = np.exp(-dt_h / P["tau_ex_h"])
    return ex * k + (1.0 - k) * exertion_target(met, P["ex_met_threshold"], P["ex_met_span"])


def step_hour_vec(P: dict, v_tot, v_ecf, cr, eff: dict, sweat, gi_loss, intake, fever_excess, phi_mult, ors=0.0,
                  ex=0.0):
    """One hour for all rows. ``ex`` = lagged exertion fraction for this hour. Returns (v_tot, v_ecf, cr, gfr)."""
    sweat_net = sweat * P["theta_sweat"] * (1 - P["phi_drink"] * phi_mult) \
        + P["fever_loss_l_day_per_c"] * np.maximum(fever_excess, 0.0) / 24.0
    drug = (P["diuretic_loss_l_day"] * eff["diuretic"] + P["sglt2_loss_l_day"] * eff["sglt2"]) / 24.0
    tot_loss = sweat_net + gi_loss + drug
    ecf_loss = sweat_net * P["ecf_frac_sweat"] + gi_loss * P["ecf_frac_gi"] + drug * P["ecf_frac_drug"]
    intake_ecf = intake * np.where(v_tot > 1e-6, v_ecf / np.maximum(v_tot, 1e-6), 1.0) + ors * P["ors_ecf_frac"]
    v_tot_n = np.maximum(v_tot + tot_loss - intake - ors - v_tot / P["tau_recover_h"], 0.0)
    v_ecf_n = np.minimum(np.maximum(v_ecf + ecf_loss - intake_ecf - v_ecf / P["tau_recover_h"], 0.0), v_tot_n)
    d = v_ecf_n / (P["ecv_frac"] * P["weight_kg"])
    h = np.where(d > 0, d ** P["hill_n"] / (d ** P["hill_n"] + P["d50"] ** P["hill_n"]), 0.0)
    e = eff["nsaid"]
    i_pg = np.where(e > 0, e / (e + P["nsaid_e50"]), 0.0)
    prot = P["a_tot"] * (P["aff_share"] * (1 - i_pg) + (1 - P["aff_share"]) * (1 - P["i_ras"] * eff["ras"]))
    gfr = P["gfr_base"] * (1 - h * (1 - prot)) * (1.0 - P["k_ex"] * ex)
    gen = P["gfr_base"] * P["cr_base"] / 100.0
    vd0 = distribution_volume_dl(P["tbw_l"], v_tot, P["vd_floor_frac"])
    vd1 = distribution_volume_dl(P["tbw_l"], v_tot_n, P["vd_floor_frac"])
    return v_tot_n, v_ecf_n, creatinine_step_vec(cr, gen, gfr, vd0, vd1), gfr


def simulate_vec(P: dict, inputs: dict, s0: dict | None = None, eff0: dict | None = None,
                 record: tuple[str, ...] = ("v_tot", "v_ecf", "cr", "gfr")) -> dict[str, np.ndarray]:
    """Run T hours for N rows. ``inputs`` values broadcast to (T, N); returns arrays of shape (T, N).

    ``eff0`` may carry the lagged exertion fraction under ``'ex'`` (default 0 = rest); ``record`` may include ``'ex'``.
    """
    N = P["gfr_base"].shape[0]
    T = max(np.asarray(v).shape[0] for v in inputs.values() if np.ndim(v) > 0)
    x = {k: np.broadcast_to(np.asarray(inputs.get(k, v), dtype=float).reshape(
        (T, -1) if np.ndim(inputs.get(k, v)) > 0 else (1, 1)), (T, N)) for k, v in INPUT_DEFAULTS.items()}
    v_tot = np.zeros(N) if s0 is None else np.asarray(s0["v_tot"], dtype=float).copy()
    v_ecf = np.zeros(N) if s0 is None else np.asarray(s0["v_ecf"], dtype=float).copy()
    cr = P["cr_base"].copy() if s0 is None else np.asarray(s0["cr"], dtype=float).copy()
    eff = {ch: (x[ch][0].copy() if eff0 is None else np.asarray(eff0[ch], dtype=float).copy()) for ch in CHANNELS}
    ex = np.zeros(N) if (eff0 is None or "ex" not in eff0) else np.asarray(eff0["ex"], dtype=float).copy()
    lag = {ch: np.exp(-math.log(2.0) / P[f"half_life_{ch}"]) for ch in CHANNELS}
    out = {k: np.empty((T, N)) for k in record}
    for t in range(T):
        for ch in CHANNELS:
            eff[ch] = eff[ch] * lag[ch] + (1 - lag[ch]) * x[ch][t]
        ex = exertion_update_vec(ex, x["met"][t], P)
        v_tot, v_ecf, cr, gfr = step_hour_vec(P, v_tot, v_ecf, cr, eff, x["sweat_l_h"][t], x["gi_loss_l_h"][t],
                                              x["intake_l_h"][t], x["fever_excess_c"][t], x["phi_mult"][t],
                                              x["ors_l_h"][t], ex)
        cur = {"v_tot": v_tot, "v_ecf": v_ecf, "cr": cr, "gfr": gfr, "ex": ex}
        for k in record:
            out[k][t] = cur[k]
    return out
