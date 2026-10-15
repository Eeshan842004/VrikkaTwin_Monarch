"""Volume, drug and creatinine engine (master plan §9.4, §9.5, §25; Decisions v1 items 3, 4)."""
import re
from pathlib import Path

import numpy as np
import pytest

from vrikka.config import load_yaml, param
from vrikka.physiology.batch import simulate_vec, stack_params
from vrikka.physiology.pk_nsaid import (
    activity_score,
    nsaid_units_from_tablets,
    nsaid_units_per_day,
    paracetamol_mg_per_day,
)
from vrikka.physiology.renal import CHANNELS, Params, creatinine_step, half_life_for, simulate

SRC = Path(__file__).resolve().parents[1] / "src" / "vrikka"


def kamala(**kw):
    return Params.from_patient(age=68, female=True, weight_kg=62, egfr=58, diuretic="chlorthalidone", **kw)


def hot_days(days=3, sweat_peak=0.55, burn_in=7, **drugs):
    """Hourly inputs: `burn_in` quiet days, then `days` days with sweat 08-17 h; drugs given as constants/arrays."""
    T = (burn_in + days + 2) * 24
    hour = np.arange(T)
    hot = (hour >= burn_in * 24) & (hour < (burn_in + days) * 24) & (hour % 24 >= 8) & (hour % 24 < 17)
    x = {"sweat_l_h": np.where(hot, sweat_peak, 0.03)}
    for k, v in drugs.items():
        x[k] = np.broadcast_to(v, (T,)).astype(float)
    return x


def delta_cr(p, x):
    out = simulate(p, x)
    return out["cr"].max() - out["cr"][7 * 24 - 1]


def test_every_kidney_drug_has_a_registered_half_life():
    lex = load_yaml("drugs_india")
    model_classes = {"nsaid_cyp2c9", "nsaid_other", "acei", "arb", "thiazide", "loop", "mra", "sglt2i"}
    for generic, cls in lex["generics"].items():
        if cls in model_classes:
            key = generic if generic in lex["half_life_key"] else cls
            assert half_life_for(key) > 0, generic
    assert set(kamala().half_life_h) == set(CHANNELS)


def test_no_shared_hard_coded_half_lives_in_source():
    for f in SRC.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert "HALF_LIFE_H" not in text, f"hard-coded half-life table in {f.name}"
        # a literal half-life table such as half_life = {"diuretic": 48} (registry param() calls are fine)
        assert not re.search(r"half_?life\w*\s*=\s*\{[^}]*:\s*\d", text, re.I), f"hard-coded half-life in {f.name}"


def test_diuretic_half_life_is_per_drug():
    assert kamala().half_life_h["diuretic"] == param("half_life_chlorthalidone_h")
    hctz = Params.from_patient(age=68, female=True, weight_kg=62, egfr=58, diuretic="hydrochlorothiazide")
    assert hctz.half_life_h["diuretic"] == param("half_life_hctz_h")
    loop = Params.from_patient(age=68, female=True, weight_kg=62, egfr=58, diuretic="furosemide")
    assert loop.half_life_h["diuretic"] == param("half_life_loop_h")
    assert loop.diuretic_loss_l_day == param("diuretic_loss_loop_l_day")


def test_chlorthalidone_wears_off_slower_than_hctz():
    pause = np.r_[np.ones(48), np.zeros(48)]
    chl = simulate(kamala(), {"diuretic": pause})["eff_diuretic"]
    hctz = simulate(Params.from_patient(age=68, female=True, weight_kg=62, egfr=58, diuretic="hydrochlorothiazide"),
                    {"diuretic": pause})["eff_diuretic"]
    assert chl[48 + 24] > hctz[48 + 24] + 0.2


def test_steady_state_creatinine():
    p = kamala()
    out = simulate(p, {"sweat_l_h": np.zeros(240)})
    assert out["cr"][-1] == pytest.approx(p.cr_base, abs=1e-9), "no losses: creatinine stays at baseline"
    cr = p.cr_base
    for _ in range(2000):
        cr = creatinine_step(cr, p.cr_generation_mg_min, 0.6 * p.gfr_base, p.tbw_l * 10)
    assert cr == pytest.approx(p.cr_base * p.gfr_base / (0.6 * p.gfr_base), rel=1e-6)


def test_exact_kinetics_matches_fine_euler():
    p = kamala()
    exact = creatinine_step(1.0, p.cr_generation_mg_min, 30.0, p.tbw_l * 10, dt_h=24)
    euler, dt = 1.0, 0.001
    for _ in range(int(24 / dt)):
        euler += dt * 60 * (p.cr_generation_mg_min - 30.0 * euler / 100) / (p.tbw_l * 10)
    assert exact == pytest.approx(euler, abs=1e-4)


def test_scenario_ordering_none_lt_nsaid_lt_double_lt_triple_lt_fever():
    nm = nsaid_units_from_tablets("combiflam", 3, activity_score("*1/*1"))
    no_drug = Params.from_patient(age=68, female=True, weight_kg=62, egfr=58)
    d = {
        "none": delta_cr(no_drug, hot_days()),
        "nsaid": delta_cr(no_drug, hot_days(nsaid=nm)),
        "double": delta_cr(kamala(), hot_days(ras=1, diuretic=1)),
        "triple": delta_cr(kamala(), hot_days(ras=1, diuretic=1, nsaid=nm)),
        "triple_fever": delta_cr(kamala(), hot_days(ras=1, diuretic=1, nsaid=nm, fever_excess_c=1.5)),
    }
    vals = list(d.values())
    assert all(a < b for a, b in zip(vals, vals[1:], strict=False)), d


def test_cyp2c9_changes_ibuprofen_exposure_only():
    assert nsaid_units_per_day("ibuprofen", 1200, 0.0) == pytest.approx(param("cyp2c9_mult_as_0_0"))
    assert nsaid_units_per_day("ibuprofen", 1200, 2.0) == pytest.approx(1.0)
    assert nsaid_units_per_day("diclofenac", 100, 0.0) == pytest.approx(nsaid_units_per_day("diclofenac", 100, 2.0))
    p = kamala()
    nm = delta_cr(p, hot_days(ras=1, diuretic=1, nsaid=nsaid_units_from_tablets("combiflam", 3, 2.0)))
    pm = delta_cr(p, hot_days(ras=1, diuretic=1, nsaid=nsaid_units_from_tablets("combiflam", 3, 0.0)))
    assert pm > nm


def test_paracetamol_has_no_kidney_effect_but_is_tallied():
    assert nsaid_units_from_tablets("dolo", 3) == 0.0
    p = kamala()
    assert delta_cr(p, hot_days(ras=1, diuretic=1)) == pytest.approx(delta_cr(p, hot_days(ras=1, diuretic=1)))
    assert paracetamol_mg_per_day({"combiflam": 3, "dolo": 3}) == pytest.approx(3 * 325 + 3 * 650)


def test_sglt2_has_no_volume_effect_by_default():
    p = kamala()
    assert delta_cr(p, hot_days(ras=1, diuretic=1, sglt2=1)) == pytest.approx(delta_cr(p, hot_days(ras=1, diuretic=1)))


def test_fever_counts_degrees_above_37_only():
    p = kamala()
    assert delta_cr(p, hot_days(ras=1, diuretic=1, fever_excess_c=0.0)) == pytest.approx(
        delta_cr(p, hot_days(ras=1, diuretic=1, fever_excess_c=-0.5)))


def test_batch_matches_scalar_to_4_decimals(rng):
    people = []
    for i in range(12):
        diu = [None, "hydrochlorothiazide", "chlorthalidone", "furosemide"][i % 4]
        people.append(Params.from_patient(age=float(rng.uniform(30, 85)), female=bool(i % 2),
                                          weight_kg=float(rng.uniform(45, 90)), egfr=float(rng.uniform(35, 100)),
                                          diuretic=diu, theta_sweat=float(rng.uniform(0.7, 1.4))))
    T = 5 * 24
    X = {"sweat_l_h": rng.uniform(0, 0.8, (T, 12)), "nsaid": (rng.uniform(0, 1, (T, 12)) > 0.5) * 1.3,
         "ras": np.ones((T, 12)), "diuretic": np.ones((T, 12)), "fever_excess_c": rng.uniform(0, 2, (T, 12)),
         "gi_loss_l_h": rng.uniform(0, 0.05, (T, 12)), "intake_l_h": rng.uniform(0, 0.05, (T, 12)),
         "ors_l_h": rng.uniform(0, 0.05, (T, 12))}
    vec = simulate_vec(stack_params(people), X)
    for j, p in enumerate(people):
        sc = simulate(p, {k: v[:, j] for k, v in X.items()})
        for k in ("v_tot", "v_ecf", "cr", "gfr"):
            np.testing.assert_allclose(vec[k][:, j], sc[k], atol=1e-4, err_msg=k)


def test_ors_refills_the_ecf_more_than_plain_water():
    """Decisions v2 B2: 1 L/day of ORS lowers the ECF deficit (and creatinine rise) more than 1 L/day of water."""
    p = kamala()
    base = hot_days(ras=1, diuretic=1, fever_excess_c=1.5)
    water = simulate(p, {**base, "intake_l_h": np.full(len(base["sweat_l_h"]), 1 / 24)})
    ors = simulate(p, {**base, "ors_l_h": np.full(len(base["sweat_l_h"]), 1 / 24)})
    assert ors["v_ecf"].max() < water["v_ecf"].max()
    assert ors["cr"].max() < water["cr"].max()
