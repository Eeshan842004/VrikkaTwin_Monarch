"""The batched twin used to build fast-clock features equals the scalar KidneyTwin (Part 4)."""
import numpy as np
import pytest

from vrikka.fastclock.labels import make_labels
from vrikka.physiology.pk_nsaid import nsaid_units_from_tablets
from vrikka.physiology.renal import Params
from vrikka.twin.batch_ukf import BatchTwin
from vrikka.twin.ukf_twin import KidneyTwin

PEOPLE = [
    dict(age=68, female=True, weight_kg=62.0, egfr=58.0, height_m=1.55, diuretic="chlorthalidone", bb=False, hr=74,
         sbp=136, ras=1.0, met_work=1.2),
    dict(age=42, female=False, weight_kg=70.0, egfr=95.0, height_m=1.70, diuretic=None, bb=False, hr=70, sbp=124,
         ras=0.0, met_work=3.0),
    dict(age=74, female=False, weight_kg=66.0, egfr=35.0, height_m=1.65, diuretic="furosemide", bb=True, hr=64,
         sbp=140, ras=1.0, met_work=1.2),
]


def params(p):
    return Params.from_patient(age=p["age"], female=p["female"], weight_kg=p["weight_kg"], egfr=p["egfr"],
                               height_m=p["height_m"], diuretic=p["diuretic"])


def day_inputs(d, p):
    h = (np.arange(24) + 8) % 24
    work = (h >= 8) & (h < 17)
    nsaid = nsaid_units_from_tablets("combiflam", 3, 2.0) if d in (2, 3) else 0.0
    return {"sweat_l_h": np.where(work, 0.6, 0.05), "met": np.where(work, p["met_work"], 1.2),
            "ras": np.full(24, p["ras"]), "diuretic": np.full(24, 1.0 if p["diuretic"] else 0.0),
            "nsaid": np.full(24, nsaid), "fever_excess_c": np.full(24, 1.5 if d == 3 else 0.0),
            "phi_mult": np.full(24, 0.7 if d == 3 else 1.0), "ors_l_h": np.full(24, 0.02 if d == 4 else 0.0)}


def test_batch_twin_matches_scalar_twin():
    rng = np.random.default_rng(3)
    scalar = [KidneyTwin(params(p), p["hr"], p["sbp"], p["bb"]) for p in PEOPLE]
    batch = BatchTwin([params(p) for p in PEOPLE], [p["hr"] for p in PEOPLE], [p["sbp"] for p in PEOPLE],
                      [p["bb"] for p in PEOPLE], [t.p.cr_base for t in scalar])
    for d in range(6):
        day = [day_inputs(d, p) for p in PEOPLE]
        for t, inp in zip(scalar, day, strict=True):
            t.predict(inp)
        batch.predict({k: np.stack([inp[k] for inp in day], axis=1) for k in day[0]})
        z = np.column_stack([np.array([p["weight_kg"] for p in PEOPLE]) - rng.uniform(0, 1.2, 3),
                             np.array([p["hr"] for p in PEOPLE]) + rng.normal(0, 4, 3),
                             np.array([p["sbp"] for p in PEOPLE]) + rng.normal(0, 8, 3)])
        z[d % 3, d % 2] = np.nan                         # one missing channel per day
        if d == 1:
            z[2, :] = np.nan                             # patient 3 measures nothing that day
        fev = np.full(3, 1.5 if d == 3 else 0.0)
        for i, t in enumerate(scalar):
            t.update(weight=z[i, 0], hr=z[i, 1], sbp=z[i, 2], fever_excess_c=float(fev[i]))
        batch.update(z, fev)
        if d == 3:
            lab = np.array([1.3, np.nan, 2.1])
            for i, t in enumerate(scalar):
                if np.isfinite(lab[i]):
                    t.update_lab(lab[i])
            batch.update_lab(lab)
        for i, t in enumerate(scalar):
            np.testing.assert_allclose(batch.x[i], t.x, rtol=1e-8, atol=1e-10, err_msg=f"x day {d} patient {i}")
            np.testing.assert_allclose(batch.P[i], t.P, rtol=1e-7, atol=1e-12, err_msg=f"P day {d} patient {i}")
            np.testing.assert_allclose(batch.cr_daily[-1][i], t.cr_daily[-1], rtol=1e-10)
            for ch in ("nsaid", "ras", "diuretic", "ex"):
                assert batch.eff[ch][i] == pytest.approx(t.eff[ch], rel=1e-12, abs=1e-15)


def test_batch_risk_uses_the_label_rule():
    """With (almost) no uncertainty the Monte-Carlo hit equals the label computed on the same daily series."""
    ps = [params(p) for p in PEOPLE]
    batch = BatchTwin(ps, [p["hr"] for p in PEOPLE], [p["sbp"] for p in PEOPLE], [p["bb"] for p in PEOPLE],
                      [p.cr_base for p in ps])
    for d in range(4):
        day = [day_inputs(d, p) for p in PEOPLE]
        batch.predict({k: np.stack([inp[k] for inp in day], axis=1) for k in day[0]})
    batch.P[:] = np.eye(5) * 1e-14
    fut = {"sweat_l_h": np.full((72, 3), 0.9), "met": np.full((72, 3), 1.2), "ras": 1.0, "diuretic": 1.0,
           "fever_excess_c": 2.0, "nsaid": nsaid_units_from_tablets("combiflam", 3, 0.0), "phi_mult": 0.7}
    base = np.array([p.cr_base for p in ps])
    r = batch.risk_72h(fut, base, n_draws=4, rng=np.random.default_rng(0))
    out = batch._run(batch.x[:, None, :], fut, record=("cr",))["cr"][:, :, 0]
    hist = np.stack(batch.cr_daily[-8:-1], axis=1)
    series = np.column_stack([hist, batch.x[:, 2], out[[23, 47, 71]].T])
    lab = make_labels(series.T, base, np.array([p["egfr"] for p in PEOPLE]))
    assert np.array_equal(r["risk"], lab["onset"][-3:].any(axis=0).astype(float))
    np.testing.assert_allclose(r["cr_peak_ratio"], out.max(axis=0) / base, rtol=1e-4)
