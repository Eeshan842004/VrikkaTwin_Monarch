"""Demo scenarios S1-S6 as tests (Decisions v1 item 16; S10, S11 are trust-layer tests in Part 6).

They replay real 2024 weather, so they are marked `data` (CI skips them; run locally).
"""
import pytest

from vrikka.config import load_yaml, param
from vrikka.twin import measurement
from vrikka.twin.replay import replay

pytestmark = pytest.mark.data
SC = load_yaml("scenarios")


@pytest.fixture(scope="module")
def s1():
    return replay("S1_riya", SC["S1_riya"], whatif_day=8)


def test_s1_riya_warns_before_aki_and_whatifs_order(s1):
    s = s1.summary()
    assert s["truth_aki_onset_day"] is not None, "the demo week produces a (simulated) AKI"
    assert s["first_red_day"] is not None and s["first_red_day"] <= s["truth_aki_onset_day"]
    w = list(s1.whatif.values())
    cont, swap, ors, pause, pm, healthy = w
    assert swap < cont, "painkiller swap lowers risk"
    assert pause <= ors <= swap, "ORS, then drug pauses, lower it further (or keep it at the floor)"
    assert pm > cont, "CYP2C9 poor metaboliser: same tablets, higher risk"
    assert healthy < cont


def test_s2_ravi_never_red():
    assert "red" not in replay("S2_ravi", SC["S2_ravi"]).levels


def test_s3_fatima_red_during_vomiting_illness():
    s = replay("S3_fatima", SC["S3_fatima"]).summary()
    assert s["first_red_day"] is not None and s["truth_aki_onset_day"] is not None
    assert s["first_red_day"] <= s["truth_aki_onset_day"]


def test_s4_iyer_hr_channel_is_down_weighted():
    sd = measurement.noise_sd(True)
    assert sd[1] == pytest.approx(param("sigma_hr_bpm") * param("sigma_hr_beta_blocker_mult"))
    assert measurement.hr_gain(True) < measurement.hr_gain(False)
    assert "red" not in replay("S4_iyer", SC["S4_iyer"]).levels


def test_s5_hydrated_stays_green_while_heat_index_rule_fires():
    r = replay("S5_hydrated", SC["S5_hydrated"])
    assert set(r.levels) == {"green"}
    assert sum(r.heat_index_rule) >= 5


def test_s6_poor_metaboliser_higher_than_normal():
    pm = replay("S6_cyp2c9", SC["S6_cyp2c9"])
    cfg = {**SC["S6_cyp2c9"], "person": {**SC["S6_cyp2c9"]["person"], "cyp2c9": "*1/*1"}}
    nm = replay("S6_normal", cfg)
    assert max(pm.risk) > max(nm.risk)
