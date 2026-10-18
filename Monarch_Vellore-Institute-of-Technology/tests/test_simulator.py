"""Synthetic world: cohort marginals, genotypes, events, labels (master plan §11, §25)."""
import ast
from pathlib import Path

import numpy as np
import pytest

from vrikka.config import load_yaml
from vrikka.fastclock.labels import episode_starts, make_labels
from vrikka.physiology.equations import kdigo_daily_matrix, kdigo_stage
from vrikka.simulator.cohort import generate_cohort, public_columns
from vrikka.simulator.devices import to_fhir_observation, to_googlefit, to_healthkit

SRC = Path(__file__).resolve().parents[1] / "src" / "vrikka"


@pytest.fixture(scope="module")
def cohort():
    return generate_cohort(3000)


def test_cohort_marginals_match_config(cohort):
    c = load_yaml("cohort")
    assert len(cohort) == 3000
    assert cohort["female"].mean() == pytest.approx(c["female"], abs=0.03)
    assert cohort["htn"].mean() == pytest.approx(c["conditions"]["htn"], abs=0.03)
    assert cohort["dm"].mean() == pytest.approx(c["conditions"]["dm"], abs=0.03)
    assert (cohort["egfr_baseline"] < 60).mean() == pytest.approx(c["conditions"]["ckd_g3"], abs=0.03)
    shares = cohort["city"].value_counts(normalize=True)
    for city, (_, _, share) in c["cities"].items():
        assert shares[city] == pytest.approx(share, abs=0.03)
    assert cohort["age"].between(30, 90).all()


def test_cyp2c9_genotypes_follow_hardy_weinberg(cohort):
    alleles = cohort["cyp2c9_genotype"].str.split("/").explode()
    freq = alleles.value_counts(normalize=True)
    assert freq["*3"] == pytest.approx(0.11, abs=0.015) and freq["*2"] == pytest.approx(0.03, abs=0.01)
    p3 = freq["*3"]
    assert (cohort["cyp2c9_genotype"] == "*3/*3").mean() == pytest.approx(p3 ** 2, abs=0.006)


def test_phi_drink_distribution(cohort):
    old = cohort["age"] >= 60
    assert cohort.loc[old, "true_phi_drink"].mean() < cohort.loc[~old, "true_phi_drink"].mean()
    assert cohort["true_phi_drink"].between(0.30, 0.95).all()


def test_hidden_columns_are_marked(cohort):
    assert "true_theta_sweat" not in public_columns(cohort)
    assert "egfr_baseline" in public_columns(cohort)


def test_daily_kdigo_matrix_equals_scalar_rule(rng):
    cr = 1.0 + np.cumsum(rng.normal(0, 0.08, (40, 30)), axis=1).clip(-0.5, 3)
    base = np.full(40, 1.0)
    m = kdigo_daily_matrix(cr, base)
    t = np.arange(30) * 24.0
    for i in range(40):
        for d in range(30):
            assert m[i, d] == kdigo_stage(t, cr[i], d, 1.0)


def test_labels_and_exclusions():
    cr = np.array([1.0, 1.0, 1.0, 1.0, 1.4, 1.5, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0])[:, None]
    lab = make_labels(cr, np.array([1.0]), np.array([58.0]))
    assert lab["onset"][4, 0] and lab["y"][1:4, 0].all() and not lab["y"][0, 0]
    assert lab["excluded"][4:6, 0].all() and lab["excluded"][6:13, 0].all()
    assert episode_starts(lab["stage"]).sum() == 1


def test_episode_counting_merges_flicker():
    stage = np.array([0, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1])[:, None]
    assert episode_starts(stage).ravel().nonzero()[0].tolist() == [1, 12]


def test_device_export_shapes():
    assert to_fhir_observation("P1", "2024-05-01", "weight", 61.2)["code"]["coding"][0]["code"] == "29463-7"
    assert to_healthkit("P1", "2024-05-01", "resting_hr", 72)["type"].endswith("RestingHeartRate")
    assert to_googlefit("P1", 1714521600000000000, "steps", 4000)["value"][0]["fpVal"] == 4000


def test_predictor_never_imports_the_simulator():
    """Anti-circularity (§11.1): twin, fast clock, slow clock, what-if, services and API code never import
    vrikka.simulator."""
    for pkg in ("twin", "fastclock", "slowclock", "whatif", "api", "physiology", "services"):
        for f in (SRC / pkg).rglob("*.py"):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                    [node.module or ""] if isinstance(node, ast.ImportFrom) else []
                assert not any(n.startswith("vrikka.simulator") for n in names), f"{f.name} imports the simulator"
