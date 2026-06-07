"""Local-mode drift() tests — stdlib-only, no mocks needed."""

import random

import pytest

from vigilai.evals import drift


def test_clear_drift_is_flagged():
    rng = random.Random(1)
    baseline = [rng.gauss(500, 50) for _ in range(40)]
    current = [rng.gauss(2000, 200) for _ in range(40)]
    out = drift(current=current, baseline=baseline)
    assert out["insufficient_data"] is False
    assert out["pct_change"] > 100
    assert out["z_score"] is not None
    assert abs(out["z_score"]) > 1.96
    assert out["drifted"] is True


def test_identical_distributions_not_flagged():
    rng = random.Random(7)
    a = [rng.gauss(1000, 100) for _ in range(40)]
    b = [rng.gauss(1000, 100) for _ in range(40)]
    out = drift(current=a, baseline=b)
    assert out["drifted"] is False


def test_tiny_but_significant_shift_not_flagged():
    """Small effect (~10 %) with low variance is statistically significant
    but below the 25 % threshold — the both-conditions rule keeps drifted
    False."""
    rng = random.Random(13)
    baseline = [rng.gauss(1000, 5) for _ in range(200)]
    current = [rng.gauss(1100, 5) for _ in range(200)]
    out = drift(current=current, baseline=baseline)
    assert out["z_score"] is not None and abs(out["z_score"]) > 1.96
    assert abs(out["pct_change"]) < 25
    assert out["drifted"] is False


def test_insufficient_data_short_circuits():
    out = drift(current=[1, 2, 3], baseline=[10, 11, 12], min_samples=10)
    assert out["insufficient_data"] is True
    assert out["drifted"] is False
    assert out["z_score"] is None
