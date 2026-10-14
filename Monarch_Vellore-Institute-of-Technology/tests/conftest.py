"""Shared pytest fixtures."""
import numpy as np
import pytest

from vrikka.config import SEED


@pytest.fixture
def rng():
    """Deterministic random generator (global seed 42, master plan §25)."""
    return np.random.default_rng(SEED)
