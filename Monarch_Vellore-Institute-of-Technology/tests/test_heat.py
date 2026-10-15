"""Heat -> sweat module (master plan §9.2, §25; Decisions v1 item 11)."""
import numpy as np
import pytest

from vrikka.config import param
from vrikka.physiology.heat import (
    build_sweat_table,
    heat_index_noaa,
    indoor_temperature,
    mean_radiant_offset,
    phs_sweat_l_h,
    wet_bulb_stull,
)

SMALL_GRID = {"tdb": np.array([25.0, 30.0, 35.0, 40.0, 45.0, 50.0]), "rh": np.array([10.0, 30.0, 60.0, 90.0]),
              "met": np.array([1.2, 2.5, 3.5]), "dtr": np.array([0.0, 8.0, 15.0])}


@pytest.fixture(scope="module")
def table():
    return build_sweat_table(62, 1.6, 0.5, grid=SMALL_GRID)


def test_plan_sanity_values_with_met_units():
    """62 kg, 1.6 m, clo 0.5, tr = tdb + 8 (§9.2): 0.61 / 0.13 / 1.0 L/h. met is in met units, not W/m2."""
    vals = phs_sweat_l_h([40, 30, 45], [48, 38, 53], [40, 60, 30], [2.5, 1.2, 3.5], 62, 1.6)
    assert vals == pytest.approx([0.61, 0.13, 1.0], abs=0.05)


def test_hotter_means_more_sweat(table):
    s, _ = table.rate(np.array([30.0, 35.0, 40.0, 45.0]), 30, 2.5, 8)
    assert np.all(np.diff(s) > 0)


def test_outside_validity_is_flagged_but_still_finite(table):
    assert (~table.valid).any(), "some hot/humid grid points are outside ISO 7933 validity"
    s, ok = table.rate(50, 90, 3.5, 15)
    assert np.isfinite(s) and not ok


def test_sweat_is_capped(table):
    s, _ = table.rate(50, 90, 3.5, 15, sweat_mult=10.0)
    assert float(s) == pytest.approx(param("sweat_cap_l_h"))


def test_radiant_offset_indoor_outdoor_and_indoor_temperature():
    assert mean_radiant_offset(800, True) == pytest.approx(param("tr_offset_sun_c"))
    assert mean_radiant_offset(800, False) == 0.0
    out = np.array([30.0, 32.0, 34.0, 36.0, 38.0])
    ind = indoor_temperature(out, roof="concrete")
    lag = int(param("indoor_lag_h"))
    assert ind[-1] == pytest.approx(out[-1 - lag] + param("indoor_offset_concrete_c"))
    assert indoor_temperature(out, cooling="ac")[-1] < ind[-1]


def test_wet_bulb_and_heat_index_reference_points():
    assert wet_bulb_stull(20, 50) == pytest.approx(13.7, abs=0.2)        # Stull 2011 worked example
    assert heat_index_noaa(32.2, 70) == pytest.approx(40.6, abs=1.0)     # NWS table: 90 F, 70 % -> 105 F
    assert heat_index_noaa(20, 50) < 21                                   # mild conditions: ~air temperature
