"""Fast clock (Part 4; Amendment 2 A2.5, A2.6; Decisions v5 C5, C6): leakage, splits, calibration, alert budgets and
reasons. Uses the committed 20-patient sample of the 2024 season."""
import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest
from sklearn.isotonic import IsotonicRegression

from vrikka.config import DATA_DIR, load_yaml
from vrikka.fastclock.alerts import AMBER, RED, alert_states, rates, tune_thresholds
from vrikka.fastclock.explain import top_reasons
from vrikka.fastclock.features import (
    B0,
    CORE,
    FULL,
    ID_COLS,
    LABEL_COLS,
    RAW,
    SPLITS,
    TWIN,
    assign_split,
    build_shard,
    forecasts,
)
from vrikka.physiology.exposure import load_season, reference_tables
from vrikka.whatif.red_flags import LANGUAGES

SAMPLE = DATA_DIR / "synthetic" / "sample"
D = 12


@pytest.fixture(scope="module")
def sample():
    people = pd.read_parquet(SAMPLE / "patients_public.parquet")
    obs = pd.read_parquet(SAMPLE / "observed_daily.parquet")
    labs = pd.read_parquet(SAMPLE / "labs.parquet")
    truth = pd.read_parquet(SAMPLE / "truth_daily.parquet")
    weather = load_season(2024)
    fc = forecasts(weather, D, seed=7)
    return people, obs, labs, truth, weather, fc, reference_tables()


def build(sample, obs=None, labs=None, truth=None):
    people, obs0, labs0, truth0, weather, fc, tables = sample
    return build_shard(people, obs0 if obs is None else obs, labs0 if labs is None else labs,
                       truth0 if truth is None else truth, weather, fc, 2024, "mismatched", 20,
                       np.random.default_rng(11), tables)


def test_feature_lists_hold_no_hidden_label_or_identifier_columns():
    assert len(CORE) <= 25, "Amendment 2 A2.6: the hybrid model uses at most 25 core features"
    for f in FULL:
        assert not f.startswith(("true_", "oracle_")) and f not in LABEL_COLS and f not in ID_COLS, f
    assert set(CORE) <= set(FULL) and not set(TWIN) & set(RAW) and set(B0) <= set(FULL)
    assert set(CORE.values()) <= {-1, 0, 1}


def test_public_patient_file_has_no_hidden_columns():
    cols = pd.read_parquet(DATA_DIR / "synthetic" / "sample" / "patients_public.parquet").columns
    assert not [c for c in cols if c.startswith("true_")]


def test_features_never_use_data_after_the_prediction_time(sample):
    """Change every observation, report, lab and truth value after day 6: features up to day 6 must not move."""
    people, obs, labs, truth, *_ = sample
    base = build(sample)
    o2 = obs.copy()
    late = o2["day"] > 6
    o2.loc[late, "weight_morning"] += 5.0
    o2.loc[late, "resting_hr"] += 30
    o2.loc[late, "rep_fever_excess_c"] = 2.0
    o2.loc[late, "rep_nsaid_on"] = True
    o2.loc[late, "rep_nsaid_generic"] = "ibuprofen"
    l2 = labs.copy()
    l2.loc[l2["day"] > 6, "creatinine_mg_dl"] *= 3
    l2 = pd.concat([l2, pd.DataFrame({"patient_id": people["patient_id"], "day": 9, "creatinine_mg_dl": 4.0,
                                      "reason": "routine"})], ignore_index=True)
    t2 = truth.copy()
    t2.loc[t2["day"] > 6, "y"] = ~t2.loc[t2["day"] > 6, "y"].astype(bool)
    pert = build(sample, o2, l2, t2)
    a = base[base["day"] <= 6].sort_values(["patient_id", "day"])[FULL].to_numpy(float)
    b = pert[pert["day"] <= 6].sort_values(["patient_id", "day"])[FULL].to_numpy(float)
    np.testing.assert_array_equal(a, b)
    later_a = base[base["day"] == 8]["wt_vs_dry_kg"].to_numpy(float)
    later_b = pert[pert["day"] == 8]["wt_vs_dry_kg"].to_numpy(float)
    m = np.isfinite(later_a)
    assert np.allclose(later_b[m] - later_a[m], 5.0), "the perturbation does reach later days"


def test_forecast_features_use_the_noisy_forecast(sample):
    people, *_, weather, fc, _ = sample
    df = build(sample)
    city = people["city"].iat[0]
    pid = people["patient_id"].iat[0]
    w = weather[city]["temperature_2m"].to_numpy(float)
    true_max = np.array([w[d * 24 + 8:d * 24 + 80].max() for d in range(D)])
    got = df[df["patient_id"] == pid].sort_values("day")["fc_tmax_72h"].to_numpy(float)
    assert not np.allclose(got, true_max), "forecast features must not equal the archived future weather"
    assert np.abs(got - true_max).max() < 10


def test_feature_rows_and_labels_line_up(sample):
    people, obs, labs, truth, *_ = sample
    df = build(sample)
    assert len(df) == len(people) * D and df[["patient_id", "day"]].duplicated().sum() == 0
    t = truth[truth["day"] < D].set_index(["patient_id", "day"])["y"].astype(bool)
    got = df.set_index(["patient_id", "day"])["y"].astype(bool)
    assert (got == t.reindex(got.index)).all()
    assert df[list(CORE)].notna().all().drop(["wt_vs_dry_kg", "hr_delta_bpm"]).all(), "only device gaps may be NaN"


def test_patient_split_is_disjoint_and_test_pool_is_separate():
    ids = np.array([f"P{i:05d}" for i in range(10000)])
    s = assign_split(ids)
    assert s.index.is_unique and set(s.unique()) == {n for n, _ in SPLITS}
    for name, frac in SPLITS:
        assert (s == name).mean() == pytest.approx(frac, abs=0.002)
    pub = pd.read_parquet(SAMPLE / "patients_public.parquet")
    assert pub["patient_id"].str.startswith("P").all() and (pub["pool"] == "train").all()


def test_isotonic_output_stays_in_unit_interval(rng):
    x, y = rng.normal(size=2000), rng.random(2000) < 0.05
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(x, y.astype(float))
    p = iso.predict(np.r_[x, -100, 100])
    assert np.all((p >= 0) & (p <= 1))


def test_alert_thresholds_respect_both_budgets(rng):
    N, Dd = 400, 120
    base = rng.beta(0.3, 30, (N, 1))
    prob = np.clip(base + rng.normal(0, 0.01, (N, Dd)) + (rng.random((N, Dd)) < 0.01) * 0.3, 0, 1)
    elig = rng.random((N, Dd)) > 0.02
    thr = tune_thresholds(prob, elig)
    red, tot = rates(alert_states(prob, elig, thr["red_threshold"], thr["amber_threshold"]), elig)
    pol = load_yaml("alert_policy")
    assert red <= pol["red_budget_per_100_patient_days"] + 1e-9
    assert tot <= pol["alert_budget_per_100_patient_days"] + 1e-9
    assert thr["amber_threshold"] <= thr["red_threshold"]


def test_hysteresis_and_dedup():
    p = np.array([[0.01, 0.30, 0.12, 0.05, 0.30, 0.01, 0.01, 0.01, 0.01, 0.40]])
    elig = np.ones_like(p, dtype=bool)
    st = alert_states(p, elig, red_thr=0.20, amber_thr=0.10, clear_ratio=0.5, dedup_days=3)
    assert st["level"][0].tolist() == [0, RED, RED, 0, RED, 0, 0, 0, 0, RED], "0.12 >= 0.5 x 0.20 keeps it red"
    assert st["red_raised"][0].nonzero()[0].tolist() == [1, 9], "re-entry on day 4 is within 72 h of day 1"
    st2 = alert_states(p, elig, red_thr=0.50, amber_thr=0.10, clear_ratio=0.5, dedup_days=3)
    assert set(st2["level"][0].tolist()) <= {0, AMBER}


def test_excluded_days_end_alerts():
    p = np.full((1, 5), 0.5)
    elig = np.array([[True, True, False, True, True]])
    st = alert_states(p, elig, 0.2, 0.1, clear_ratio=0.5, dedup_days=0)
    assert st["level"][0, 2] == 0 and st["red_raised"][0].nonzero()[0].tolist() == [0, 3]


def test_reasons_map_to_i18n_keys_in_every_language(rng):
    X = pd.DataFrame(rng.normal(size=(500, len(CORE))), columns=list(CORE))
    y = (X["mc_risk_72h"] + 0.5 * X["rep_fever_c"] + rng.normal(0, 0.5, 500) > 1.5).astype(int)
    b = lgb.train({"objective": "binary", "verbosity": -1, "min_data_in_leaf": 20}, lgb.Dataset(X, y), 20)
    for reasons in top_reasons(b, X.head(20)):
        assert len(reasons) <= 3
        for r in reasons:
            assert r["contribution"] > 0
            for lang in LANGUAGES:
                assert r["i18n_key"] in load_yaml(f"i18n/{lang}"), (lang, r["i18n_key"])
    for lang in LANGUAGES:
        missing = [f for f in CORE if f"reason.{f}" not in load_yaml(f"i18n/{lang}")]
        assert not missing, (lang, missing)
