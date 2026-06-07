"""Sample-based drift detection.

This SDK function takes two lists of metric samples (e.g. latencies in ms,
or completion-token counts) and reports whether they differ enough to call
drift. It is INTENTIONALLY simpler than the backend's DriftDetector — the
backend version reads from audit_logs and computes three signals at once.
For log-backed drift, use the dashboard path: logger.evals.run_suite(...).

We avoid scipy here so the SDK stays light. The two-sample test below is
a non-parametric rank-sum approximation good enough for sanity-checking
mid-pipeline samples; if you want the full p-value pipeline, run the
dashboard suite.
"""

from __future__ import annotations

from statistics import mean
from typing import Iterable


def _pct_change(baseline: float, current: float) -> float:
    if baseline == 0:
        return 0.0 if current == 0 else 100.0
    return ((current - baseline) / baseline) * 100.0


def _ranksum_z(a: list[float], b: list[float]) -> float | None:
    """Wilcoxon rank-sum z-score (Mann-Whitney's normal approximation).

    Returns the signed z; a |z| above ~1.96 corresponds to p < 0.05.
    Returns None when one side is empty.
    """
    if not a or not b:
        return None
    combined = [(v, 0) for v in a] + [(v, 1) for v in b]
    combined.sort(key=lambda t: t[0])
    # Average ranks for ties.
    ranks = [0.0] * len(combined)
    i = 0
    while i < len(combined):
        j = i
        while j + 1 < len(combined) and combined[j + 1][0] == combined[i][0]:
            j += 1
        avg = (i + j) / 2 + 1  # ranks are 1-based; mean of [i+1 .. j+1]
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    r_a = sum(ranks[idx] for idx, (_, src) in enumerate(combined) if src == 0)
    n_a, n_b = len(a), len(b)
    mu = n_a * (n_a + n_b + 1) / 2
    sigma2 = n_a * n_b * (n_a + n_b + 1) / 12
    if sigma2 == 0:
        return None
    return (r_a - mu) / (sigma2 ** 0.5)


def detect(
    current: Iterable[float],
    baseline: Iterable[float],
    pct_threshold: float = 25.0,
    min_samples: int = 10,
) -> dict:
    """Compare two samples and report drift.

    Args:
        current:        recent metric samples (e.g. latencies last 1h)
        baseline:       prior-period samples to compare against
        pct_threshold:  effect-size threshold, default 25% on the mean
        min_samples:    short-circuit with ``insufficient_data=True`` if
                        either side has fewer than this many samples

    Returns a dict mirroring the dashboard's drift signal:
        baseline_mean, current_mean, pct_change, z_score, drifted,
        insufficient_data

    `drifted=True` requires BOTH effect size and statistical significance
    (|z| > 1.96, ~p < 0.05) — same both-conditions rule as the dashboard
    detector. For log-backed multi-signal drift, use logger.evals.run_suite.
    """
    cur = list(current)
    base = list(baseline)
    if len(cur) < min_samples or len(base) < min_samples:
        return {
            "baseline_mean": mean(base) if base else 0.0,
            "current_mean": mean(cur) if cur else 0.0,
            "pct_change": 0.0,
            "z_score": None,
            "drifted": False,
            "insufficient_data": True,
            "min_samples": min_samples,
        }
    b_mean = mean(base)
    c_mean = mean(cur)
    pct = _pct_change(b_mean, c_mean)
    z = _ranksum_z(base, cur)
    drifted = (
        abs(pct) >= pct_threshold
        and z is not None
        and abs(z) > 1.96
    )
    return {
        "baseline_mean": b_mean,
        "current_mean": c_mean,
        "pct_change": pct,
        "z_score": z,
        "drifted": drifted,
        "insufficient_data": False,
    }
