"""Slow clock (Part 5): Bayesian eGFR slope, AKI penalty rules (Decisions v5 C3), treatment effects, ranges only,
KFRE validity, and the wording that must accompany a projection."""
import numpy as np
import pytest

from vrikka.config import overrides, param
from vrikka.physiology.equations import creatinine_from_egfr
from vrikka.slowclock.bayes_slope import fit, fit_from_labs, prior_group
from vrikka.slowclock.kfre import kfre_panel
from vrikka.slowclock.projection import (
    AkiEpisode,
    Scenario,
    aki_effect,
    compare,
    grid,
    project,
    treatment_effect,
    wording,
    years_to_threshold,
)


def test_prior_group_follows_diabetes_and_albuminuria():
    assert prior_group(dm=False) == "htn_no_dm"
    assert prior_group(dm=True, uacr_mg_g=10) == "dm_htn"
    assert prior_group(dm=True, uacr_mg_g=param("albuminuria_uacr_mg_g")) == "dkd_albuminuria"
    assert prior_group(dm=False, uacr_mg_g=300) == "htn_no_dm"        # albuminuria prior is from a diabetic cohort


def test_no_observations_returns_the_prior():
    post = fit([], egfr_now=58.0, dm=True)
    assert post.mean[0] == 58.0 and post.mean[1] == param("slope_prior_dm_htn")
    assert post.slope_sd == pytest.approx(param("slope_prior_sd"))


def test_posterior_learns_a_steep_personal_slope_from_serial_values():
    rng = np.random.default_rng(1)
    t = np.arange(-5.0, 0.01, 0.25)
    obs = [(float(x), float(70 - 4.0 * (x + 5) + rng.normal(0, param("egfr_obs_sd")))) for x in t]
    post = fit(obs, egfr_now=obs[-1][1], dm=False)
    assert post.slope == pytest.approx(-4.0, abs=0.8)                # prior was -1.5; the data win
    assert post.slope_sd < 0.5 * param("slope_prior_sd")
    lo, hi = post.slope_range()
    assert lo < post.slope < hi


def test_values_taken_while_creatinine_is_changing_are_skipped():
    cr = creatinine_from_egfr(60, 60, True)
    labs = [(-2.0, cr), (-1.0, cr + 0.02), (-0.5, cr + 0.45), (0.0, cr + 0.03)]   # -0.5: AKI-time value
    post = fit_from_labs(labs, age_now=60, female=True, dm=False)
    assert post.n_obs == 3 and post.skipped == 1


def test_projection_is_ranges_only_and_ordered():
    post = fit([(0.0, 45.0)], egfr_now=45.0, dm=True)
    pr = project(post)
    assert pr.t_years[0] == 0 and pr.t_years[-1] == pytest.approx(param("projection_years"))
    assert np.all(pr.low <= pr.median) and np.all(pr.median <= pr.high)
    assert np.all(pr.high[1:] - pr.low[1:] > 0), "every projected value is a range, never a single number"
    g3 = pr.years_to["g3a"]
    assert g3["text"] == "already below"                              # 45 is below 60 in (almost) every draw
    g4 = pr.years_to["g4"]
    assert g4["low"] <= g4["median"] <= g4["high"]


def test_aki_penalty_is_applied_once_for_any_aki_with_capped_extra_episodes():
    t = grid()
    one = aki_effect(t, [AkiEpisode(0.0)], include_steps=False)
    two = aki_effect(t, [AkiEpisode(0.0), AkiEpisode(0.0)], include_steps=False)
    three = aki_effect(t, [AkiEpisode(0.0)] * 3, include_steps=False)
    assert np.all(one <= 0) and one[-1] < 0
    assert np.allclose(two, one * (1 + param("aki_penalty_extra_episode_mult")))
    assert np.allclose(three, two), "at most aki_penalty_max_episodes episodes count"
    with overrides(aki_penalty_extra_episode_mult=0.0):              # the source's yes/no reading
        assert np.allclose(aki_effect(t, [AkiEpisode(0.0)] * 2, include_steps=False), one)


def test_aki_penalty_fades_and_scales_by_stage():
    t = grid()
    tau = param("aki_penalty_tau_years")
    full = param("aki_slope_penalty") * param("aki_penalty_stage1_mult") * tau
    one = aki_effect(t, [AkiEpisode(0.0)], include_steps=False)
    assert one[-1] == pytest.approx(full * (1 - np.exp(-t[-1] / tau)))
    old = aki_effect(t, [AkiEpisode(-10.0)], include_steps=False)    # 10 years ago: almost faded
    assert abs(old[-1]) < 0.01 * abs(one[-1])
    s3 = aki_effect(t, [AkiEpisode(0.0, stage=3)], include_steps=False)
    assert s3[-1] < one[-1]


def test_future_aki_adds_a_one_off_step_and_past_aki_does_not():
    t = grid()
    fut = aki_effect(t, [AkiEpisode(1.0, stage=2)]) - aki_effect(t, [AkiEpisode(1.0, stage=2)], include_steps=False)
    assert fut[t < 1.0].max() == 0 and fut[t >= 1.0].min() == pytest.approx(-param("aki_step_stage2"))
    past = aki_effect(t, [AkiEpisode(-1.0)]) - aki_effect(t, [AkiEpisode(-1.0)], include_steps=False)
    assert np.all(past == 0)


def test_sglt2i_dip_then_slower_decline():
    t = grid()
    e = treatment_effect(t, Scenario(sglt2i_start_years=0.0))
    assert e[0] == pytest.approx(-param("sglt2i_initial_dip"))
    j = int(np.argmin(np.abs(t - 10)))
    assert e[j] == pytest.approx(-param("sglt2i_initial_dip") + param("sglt2i_slope_effect") * 10)


def test_compare_aki_scenario_uses_common_draws():
    post = fit([], egfr_now=75.0, dm=True)
    d = compare(post, Scenario(), Scenario(episodes=[AkiEpisode(0.2)], label="one AKI this season"))
    assert d["high"] < 0 and d["low"] <= d["median"] <= d["high"]


def test_years_to_threshold_edges():
    t = np.array([0.0, 1.0, 2.0])
    eg = np.array([[50, 49, 48], [70, 65, 59], [80, 79, 78]], dtype=float)
    yt = years_to_threshold(t, eg, 60.0)
    assert yt[0] == 0 and yt[1] == 2 and np.isinf(yt[2])


def test_kfre_only_where_valid():
    ok = kfre_panel(65, True, 35, 300)
    assert ok["valid"] and ok["risk_2y"] == pytest.approx(0.0305, abs=1e-4) and ok["risk_5y"] == pytest.approx(
        0.1132, abs=1e-4)
    assert ok["referral_prompt"]
    assert kfre_panel(65, True, 75, 300) == {"valid": False, "reason_key": "kfre.egfr_too_high"}
    assert kfre_panel(65, True, 35, None)["reason_key"] == "kfre.no_uacr"
    assert kfre_panel(65, True, 8, 300)["reason_key"] == "kfre.egfr_too_low"


def test_wording_keys_for_people_without_diabetes():
    assert "slow.aki_extrapolated" in wording(dm=False, has_aki_scenario=True)
    assert "slow.aki_extrapolated" not in wording(dm=True, has_aki_scenario=True)
    assert wording(dm=True, has_aki_scenario=False) == ["slow.ranges_only"]


def test_overrides_refuse_values_outside_the_registered_range():
    with pytest.raises(ValueError):
        with overrides(aki_penalty_tau_years=50.0):
            pass


def test_projection_never_goes_below_zero():
    post = fit([(0.0, 25.0)], egfr_now=25.0, dm=True, uacr_mg_g=300)
    pr = project(post)
    assert pr.low.min() >= 0
