"""Engine revision of 16 Oct 2026: mass-conserving haemoconcentration (Decisions v5 C1) and the exertional GFR fall
(Decisions v4 2b / v5 C2; both pre-registered in Amendment 2 A2.4)."""
import math
from dataclasses import replace

import numpy as np
import pytest
from scipy.integrate import solve_ivp

from vrikka.physiology.batch import creatinine_step_vec, simulate_vec, stack_params
from vrikka.physiology.renal import (
    Params,
    creatinine_step,
    distribution_volume_dl,
    exertion_target,
    simulate,
)
from vrikka.twin.ukf_twin import KidneyTwin

TBW, GFR, CR0 = 38.5, 100.0, 0.9          # healthy adult, v5 C1 acceptance case
GEN = GFR * CR0 / 100.0                    # mg/min at steady state


def ravi(**kw):
    return Params.from_patient(age=30, female=False, weight_kg=70.0, height_m=1.70, egfr=105.0, **kw)


def shift(met_work=3.5, hours=(8, 17), days=2):
    """Hourly met: rest (home) except a work shift from ``hours[0]`` to ``hours[1]`` on day 1."""
    met = np.full(24 * days, 1.2)
    met[hours[0]:hours[1]] = met_work
    return met


# ----------------------------------------------------------------------------------------- C1: haemoconcentration
def test_two_litre_loss_over_nine_hours_matches_the_mass_conserving_ode():
    """v5 C1 acceptance test. A 2 L loss (linear over 9 h) at constant GFR raises creatinine by a few per cent and
    the hourly scheme agrees with the continuous ODE dM/dt = G - GFR x M/(100 Vd(t)). (v5 quotes 'about +2.5 %'; the
    exact value for this loss profile is +2.9 %.)"""
    def vd_at(t):
        return (TBW - 2.0 * min(t / 9.0, 1.0)) * 10.0

    ref = solve_ivp(lambda t, y: [60.0 * GEN - 0.6 * GFR * y[0] / vd_at(t)], [0, 9], [CR0 * vd_at(0)],
                    rtol=1e-10, atol=1e-12)
    cr_ref = ref.y[0, -1] / vd_at(9)
    cr = CR0
    for h in range(9):
        cr = creatinine_step(cr, GEN, GFR, vd_at(h), 1.0, vd_at(h + 1))
    assert cr == pytest.approx(cr_ref, rel=1e-4)
    assert 1.020 < cr / CR0 < 1.035, cr / CR0
    # the vector form is the same scheme
    cv = np.array([CR0])
    for h in range(9):
        cv = creatinine_step_vec(cv, GEN, GFR, np.array([vd_at(h)]), np.array([vd_at(h + 1)]))
    assert cv[0] == pytest.approx(cr, rel=1e-12)


def test_shrinking_vd_inside_the_old_ode_has_no_concentration_effect():
    """The v4 formulation (smaller Vd in the unchanged ODE) leaves a constant-GFR steady state untouched; that is why
    v5 replaced it. Guard against regressing to it."""
    cr = CR0
    for h in range(9):
        cr = creatinine_step(cr, GEN, GFR, (TBW - 2.0 * (h + 1) / 9.0) * 10.0)     # volume only enters the rate
    assert cr == pytest.approx(CR0, abs=1e-12)


def test_constant_volume_reproduces_the_old_kinetics_exactly():
    vd = TBW * 10.0
    k = 0.6 * 70.0 / vd
    css = 100.0 * GEN / 70.0
    old = css + (1.1 - css) * math.exp(-k)
    assert creatinine_step(1.1, GEN, 70.0, vd) == old
    assert creatinine_step(1.1, GEN, 70.0, vd, 1.0, vd) == old
    assert creatinine_step_vec(np.array([1.1]), GEN, 70.0, np.array([vd]), np.array([vd]))[0] == old


def test_engine_without_water_loss_equals_the_old_formula():
    """v_tot stays 0, so only the GFR (here from exertion) moves creatinine, through the old formula."""
    p = ravi()
    out = simulate(p, {"met": shift()})
    vd = p.tbw_l * 10.0
    cr = p.cr_base
    for h in range(48):
        k = 0.6 * out["gfr"][h] / vd
        css = 100.0 * p.cr_generation_mg_min / out["gfr"][h]
        cr = css + (cr - css) * math.exp(-k)
        assert out["cr"][h] == pytest.approx(cr, abs=1e-12)
    assert np.all(out["v_tot"] == 0.0)


def test_creatinine_mass_is_conserved_when_the_volume_changes():
    for vd0, vd1 in ((385.0, 365.0), (365.0, 385.0)):
        cr_n = creatinine_step(1.0, 0.0, 0.0, vd0, 1.0, vd1)           # no generation, no clearance
        assert cr_n * vd1 == pytest.approx(1.0 * vd0, rel=1e-12)
        cr_v = creatinine_step_vec(np.array([1.0]), 0.0, np.array([0.0]), np.array([vd0]), np.array([vd1]))
        assert cr_v[0] * vd1 == pytest.approx(1.0 * vd0, rel=1e-12)


def test_distribution_volume_follows_total_body_water_with_a_floor():
    assert distribution_volume_dl(TBW, 0.0) == pytest.approx(385.0)
    assert distribution_volume_dl(TBW, 2.0) == pytest.approx(365.0)
    assert distribution_volume_dl(TBW, 20.0) == pytest.approx(0.8 * 385.0)        # floor: 0.8 x TBW


def test_water_loss_now_concentrates_creatinine_in_the_engine():
    """Same GFR series, old fixed-Vd formula vs the engine: the engine is higher by the haemoconcentration."""
    p = replace(ravi(), phi_drink=0.0)                                # nothing drunk back: ~4 L lost in 9 h
    sweat = np.zeros(48)
    sweat[8:17] = 0.45
    out = simulate(p, {"sweat_l_h": sweat})
    assert out["v_tot"].max() > 2.5
    vd, cr, old = p.tbw_l * 10.0, p.cr_base, []
    for g in out["gfr"]:
        k, css = 0.6 * g / vd, 100.0 * p.cr_generation_mg_min / g
        cr = css + (cr - css) * math.exp(-k)
        old.append(cr)
    old = np.array(old)
    assert out["cr"].max() > old.max() * 1.01, "haemoconcentration must add a few per cent on top of the GFR fall"
    assert out["cr"][8 + 9 - 1] > old[8 + 9 - 1], "at the end of the shift the engine is above the fixed-Vd series"


# ----------------------------------------------------------------------------------------- C2: exertion
def test_exertion_fraction_is_zero_at_rest_and_saturates_above_threshold_plus_span():
    assert exertion_target(1.2) == 0.0 and exertion_target(2.0) == 0.0
    assert exertion_target(3.0) == pytest.approx(0.5) and exertion_target(4.0) == pytest.approx(1.0)
    assert exertion_target(9.0) == 1.0


def test_exertional_gfr_fall_is_lagged_and_proportional_to_k_ex():
    p = ravi()
    out = simulate(p, {"met": shift(3.5)})
    full = 0.75                                                      # (3.5 - 2) / 2
    lag = math.exp(-1.0 / p.tau_ex_h)
    assert out["ex"][7] == 0.0
    assert out["ex"][8] == pytest.approx((1 - lag) * full)           # first hour of work: 63 % of the way
    assert out["ex"][16] == pytest.approx(full * (1 - lag ** 9), rel=1e-9)
    assert out["ex"][17] == pytest.approx(out["ex"][16] * lag, rel=1e-9)   # decays after the shift
    assert out["gfr"][16] == pytest.approx(p.gfr_base * (1 - p.k_ex * out["ex"][16]))
    assert out["gfr"][16] < out["gfr"][7]


def test_exertion_raises_creatinine_in_the_shift_and_it_recovers_by_next_morning():
    p = ravi()
    out = simulate(p, {"met": shift(3.5)})
    rise = out["cr"][16] - p.cr_base                                 # end of shift (17:00)
    residual = out["cr"][24 + 7] - p.cr_base                         # next 08:00
    assert 0.10 < rise < 0.18, rise                                  # a ~19 % GFR fall for 9 h at Cr 0.9
    assert 0 < residual < 0.15 * rise, "the morning value is the sustained-injury signal, not the transient rise"
    off = simulate(replace(p, k_ex=0.0), {"met": shift(3.5)})
    assert np.allclose(off["cr"], p.cr_base) and np.allclose(off["gfr"], p.gfr_base)


def test_home_based_people_are_unaffected_by_exertion():
    p = ravi()
    for met in (1.2, 1.3, 2.0):
        out = simulate(p, {"met": np.full(48, met)})
        assert np.all(out["ex"] == 0.0) and np.allclose(out["cr"], p.cr_base)


def test_batch_engine_matches_scalar_with_exertion_and_water_loss(rng):
    people = [ravi(theta_sweat=float(t)) for t in (0.8, 1.0, 1.3)]
    T = 72
    X = {"sweat_l_h": np.tile(np.where(np.arange(T) % 24 >= 8, 0.4, 0.05)[:, None], (1, 3)),
         "met": np.tile(np.where((np.arange(T) % 24 >= 8) & (np.arange(T) % 24 < 17), 3.2, 1.2)[:, None], (1, 3))}
    vec = simulate_vec(stack_params(people), X, record=("v_tot", "v_ecf", "cr", "gfr", "ex"))
    for j, p in enumerate(people):
        sc = simulate(p, {k: v[:, j] for k, v in X.items()})
        for k in ("v_tot", "v_ecf", "cr", "gfr", "ex"):
            np.testing.assert_allclose(vec[k][:, j], sc[k], atol=1e-9, err_msg=k)


def test_twin_carries_the_exertion_state_between_days():
    twin = KidneyTwin(ravi(), hr_base=70, sbp_base=125)
    twin.predict({"met": 3.5})                                       # 24 h at met 3.5
    assert twin.eff["ex"] == pytest.approx(0.75 * (1 - math.exp(-24.0 / twin.p.tau_ex_h)), rel=1e-9)
    twin2 = KidneyTwin(ravi(), hr_base=70, sbp_base=125)
    twin2.predict({"met": 1.2})
    assert twin2.eff["ex"] == 0.0
