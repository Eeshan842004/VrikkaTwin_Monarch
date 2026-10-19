"""Personal twin and Monte-Carlo risk (master plan §10, §25; Decisions v1 item 5, v2 A-5a/A-5b)."""
import numpy as np
import pytest

from vrikka.config import param
from vrikka.fastclock.labels import make_labels
from vrikka.physiology.pk_nsaid import nsaid_units_from_tablets
from vrikka.physiology.renal import Params, simulate
from vrikka.twin import measurement
from vrikka.twin.risk_mc import aki_risk_72h
from vrikka.twin.ukf_twin import KidneyTwin


def day_sweat(peak):
    h = (np.arange(24) + 8) % 24                      # twin days run 08:00 -> 08:00
    return np.where((h >= 8) & (h < 17), peak, 0.04)


def riya_params(**kw):
    return Params.from_patient(age=68, female=True, weight_kg=62, egfr=58, **kw)


def run_twin(theta_true, phi_true, phi_prior=None, peak=0.8, days=7, lab_day=5, seed=0):
    rng = np.random.default_rng(seed)
    truth = riya_params()
    truth.theta_sweat, truth.phi_drink = theta_true, phi_true
    twin_p = riya_params()
    if phi_prior is not None:
        twin_p.phi_drink = phi_prior
    twin = KidneyTwin(twin_p, hr_base=74, sbp_base=130)
    out = simulate(truth, {"sweat_l_h": np.tile(day_sweat(peak), days)})
    for d in range(days):
        twin.predict({"sweat_l_h": day_sweat(peak)})
        i = (d + 1) * 24 - 1
        twin.update(weight=62 - out["v_tot"][i] + rng.normal(0, param("sigma_weight_kg")),
                    hr=74 + param("k_hr") * out["v_ecf"][i] + rng.normal(0, param("sigma_hr_bpm")))
        if lab_day is not None and d + 1 == lab_day:
            twin.update_lab(out["cr"][i] * (1 + rng.normal(0, param("cr_lab_cv"))))
    return twin, out


def test_theta_learned_within_20pct_on_average_in_7_days():
    """Hot outdoor week + one lab (plan §25). Reported honestly: this holds for the mean over 10 seeds; individual
    seeds reach it 8/10 times (PROGRESS.md, Part 3)."""
    est = np.array([run_twin(1.4, 0.60, seed=s)[0].theta for s in range(10)])
    assert abs(est.mean() - 1.4) / 1.4 <= 0.20
    assert (est > 1.0).mean() >= 0.8, "the estimate moves toward the truth for most people"


def test_twin_separates_low_and_high_drinkers():
    """Decisions v2 A-5b: same weather, phi 0.45 vs 0.75 -> learned theta higher for the low drinker, within 7 days."""
    for s in range(5):
        low = run_twin(1.0, 0.45, phi_prior=0.60, seed=s, lab_day=None)[0].theta
        high = run_twin(1.0, 0.75, phi_prior=0.60, seed=s, lab_day=None)[0].theta
        assert low > high


def test_lab_pulls_creatinine_toward_the_lab_value():
    twin = KidneyTwin(riya_params(), hr_base=74, sbp_base=130)
    twin.predict({"sweat_l_h": day_sweat(0.3)})
    before = twin.x[2]
    twin.update_lab(before + 0.5)
    assert before < twin.x[2] <= before + 0.5
    assert twin.cr_daily[-1] == pytest.approx(twin.x[2])


def test_missing_channels_do_not_crash_and_leave_state_finite():
    twin = KidneyTwin(riya_params(), hr_base=74, sbp_base=130)
    for obs in ({}, {"weight": 61.8}, {"hr": 80.0}, {"weight": np.nan, "hr": np.nan, "sbp": 128.0}):
        twin.predict({"sweat_l_h": day_sweat(0.5)})
        twin.update(**obs)
        assert np.all(np.isfinite(twin.x)) and np.all(np.linalg.eigvalsh(twin.P) > -1e-9)


def test_beta_blocker_blunts_hr_and_widens_its_noise():
    assert measurement.hr_gain(True) == pytest.approx(param("k_hr") * param("k_hr_beta_blocker_mult"))
    assert measurement.noise_sd(True)[1] == pytest.approx(param("sigma_hr_bpm") * param("sigma_hr_beta_blocker_mult"))


def test_fever_is_inside_the_hr_model():
    x = np.array([[0.0, 0.0, 1.0, 0.0, 62.0]])
    assert measurement.hx(x, 74, 130, False, fever_excess_c=1.5)[0, 1] == pytest.approx(
        74 + param("hr_fever_bpm_per_c") * 1.5)


def hot_twin(days=5):
    twin = KidneyTwin(riya_params(diuretic="chlorthalidone"), hr_base=74, sbp_base=130)
    for _ in range(days):
        twin.predict({"sweat_l_h": day_sweat(0.8), "ras": 1, "diuretic": 1})
    return twin


def test_mc_risk_ordering_matches_plan():
    """§10.2 ordering: continue < fever + paracetamol < fever + ibuprofen < fever + ibuprofen (CYP2C9 *3/*3)."""
    twin = hot_twin()
    base = {"sweat_l_h": np.tile(day_sweat(0.8), 3), "ras": 1, "diuretic": 1}
    fever = {**base, "fever_excess_c": 1.5}
    nm, pm = nsaid_units_from_tablets("combiflam", 3, 2.0), nsaid_units_from_tablets("combiflam", 3, 0.0)
    r = [aki_risk_72h(twin, s, baseline_cr=twin.p.cr_base, n_draws=200) for s in
         (base, fever, {**fever, "nsaid": nm}, {**fever, "nsaid": pm})]
    assert r[0] <= r[1] <= r[2] <= r[3] and r[3] > r[0], r


def test_twin_risk_and_label_use_the_same_kdigo_rule():
    """With (almost) no uncertainty, the Monte-Carlo hit must equal the label computed on the same daily series."""
    twin = hot_twin()
    twin.P = np.eye(5) * 1e-12
    fut = {"sweat_l_h": np.tile(day_sweat(1.0), 3), "ras": 1, "diuretic": 1, "fever_excess_c": 2.0,
           "nsaid": nsaid_units_from_tablets("combiflam", 3, 0.0)}
    prob, series = aki_risk_72h(twin, fut, baseline_cr=twin.p.cr_base, n_draws=5, return_draws=True)
    lab = make_labels(series[:1].T, np.array([twin.p.cr_base]), np.array([58.0]))
    expected = bool(lab["onset"][-3:, 0].any())
    assert prob == float(expected)
