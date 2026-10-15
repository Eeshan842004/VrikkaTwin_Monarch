"""Kidney equations: golden values and KDIGO rules (master plan §9.3, §25; Decisions v1 item 5)."""
import numpy as np
import pytest

from vrikka.physiology.equations import (
    baseline_creatinine,
    creatinine_from_egfr,
    creatinine_to_mg_dl,
    daily_samples,
    egfr_ckd_epi_2021,
    kdigo_daily_stages,
    kdigo_stage,
    kfre_4var,
    kfre_is_valid,
    uacr_to_mg_g,
)


def test_ckd_epi_2021_golden_values():
    assert egfr_ckd_epi_2021(1.0, 60, True) == pytest.approx(64.5, abs=0.05)
    assert egfr_ckd_epi_2021(1.2, 50, False) == pytest.approx(73.7, abs=0.05)


def test_ckd_epi_inverse_round_trips():
    for egfr, age, female in [(58, 68, True), (95, 42, False), (35, 74, False), (120, 30, True)]:
        assert egfr_ckd_epi_2021(creatinine_from_egfr(egfr, age, female), age, female) == pytest.approx(egfr, rel=1e-9)


def test_kfre_golden_values_and_agreement_with_kfre_package():
    kfre = pytest.importorskip("kfre")
    two, five = kfre_4var(65, True, 35, 300, 2), kfre_4var(65, True, 35, 300, 5)
    assert two == pytest.approx(0.0305, abs=5e-5) and five == pytest.approx(0.1132, abs=5e-5)
    for args in [(55, False, 25, 800), (72, True, 50, 40), (40, True, 15, 1500)]:
        for years in (2, 5):
            ours = kfre_4var(*args, years=years)
            ref = kfre.kfre_person(age=args[0], is_male=args[1], eGFR=args[2], uACR=args[3],
                                   is_north_american=False, years=years)
            assert ours == pytest.approx(float(ref), abs=1e-6)


def test_kfre_validity_window():
    assert kfre_is_valid(35, 300) and not kfre_is_valid(65, 300) and not kfre_is_valid(35, None)


def kd(cr, baseline=None, step_h=24):
    t = np.arange(len(cr)) * step_h
    return kdigo_stage(t, np.array(cr, dtype=float), len(cr) - 1, baseline)


def test_kdigo_rules():
    assert kd([4.2, 4.2, 4.2], baseline=4.2) == 0, "stable CKD with Cr >= 4 is not AKI"
    assert kd([1.0, 1.35], step_h=48) == 1, "+0.3 within 48 h"
    assert kd([1.0, 1.0, 1.0, 1.29]) == 0, "+0.29 is below the threshold"
    assert kd([1.0, 1.55]) == 1, "1.5x baseline"
    assert kd([1.0, 2.1]) == 2
    assert kd([2.0, 4.1]) == 3, "Cr >= 4 upgrades an existing AKI"
    assert kd([1.0, 3.1]) == 3


def test_creatinine_unit_detection():
    v, conv = creatinine_to_mg_dl(88)
    assert conv and v == pytest.approx(0.995, abs=1e-3)
    assert creatinine_to_mg_dl(1.1) == (1.1, False)
    assert uacr_to_mg_g(10, "mg/mmol") == pytest.approx(88.4)


def test_daily_sampling_reads_one_value_at_0800():
    t = np.arange(0, 72, 1.0)                    # three days of hourly values
    cr = 1.0 + 0.001 * t
    td, cd = daily_samples(t, cr)
    assert list(td) == [8.0, 32.0, 56.0]
    assert np.allclose(cd, 1.0 + 0.001 * td)


def test_daily_stages_ignore_intra_day_peaks():
    """A brief hourly spike that has resolved by 08:00 must not create an AKI label (same rule as the twin)."""
    t = np.arange(0, 96, 1.0)
    cr = np.full_like(t, 1.0)
    cr[(t > 34) & (t < 44)] = 1.5                # spike between the day-1 and day-2 samples
    _, st = kdigo_daily_stages(t, cr, baseline=1.0)
    assert st.max() == 0
    cr[(t >= 56)] = 1.4                          # sustained rise caught at the next 08:00 sample
    _, st = kdigo_daily_stages(t, cr, baseline=1.0)
    assert st.max() == 1


def test_baseline_rule():
    labs = [(-300, 1.1), (-120, 1.0), (-30, 1.2), (-5, 2.0)]
    stable = [True, True, True, False]               # the last value was during an illness
    assert baseline_creatinine(labs, 0, 68, True, stable) == (pytest.approx(1.1), "mean_last_2")
    assert baseline_creatinine([(-400, 1.0), (-30, 1.3)], 0, 68, True) == (pytest.approx(1.3), "single")
    value, src = baseline_creatinine([], 0, 68, True)
    assert src == "back_calculated" and egfr_ckd_epi_2021(value, 68, True) == pytest.approx(75.0)
