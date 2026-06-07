"""Drift detection: statistical comparison of recent model behaviour
against a baseline window.

Three signals are computed from ``audit_logs``:

1. **Latency** — compare p95 between the two windows. Flag when both the
   percent change in p95 exceeds the threshold AND a two-sample Mann-Whitney
   U test on the raw samples returns p < 0.05.
2. **Response length** — same idea on ``completion_tokens``.
3. **Error rate** — proportion of logs with ``status='error'``. Flag when the
   delta in percentage points exceeds the threshold. No p-value here — a
   proportion test is overkill for the small numbers we expect, and the
   percentage-point delta is the directly interpretable quantity for operators.

The "both conditions" rule (effect size AND p-value) is deliberate. With
large samples, a 2% shift in latency p95 is trivially "significant"; with
small samples, a real 50% shift may not reach p < 0.05. Requiring both keeps
the signal honest.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
from scipy import stats
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AuditLog

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# A window with fewer than this many logs is considered too noisy to compare;
# we skip the stats and return ``insufficient_data=True`` instead of inventing
# a p-value from 3 samples.
MIN_SAMPLES_PER_WINDOW = 10

# Defaults match the prompt; per-instance overrides via constructor.
DEFAULT_LATENCY_PCT_THRESHOLD = 25.0       # percent shift in p95
DEFAULT_LENGTH_PCT_THRESHOLD = 25.0        # percent shift in mean
DEFAULT_ERROR_RATE_DELTA_THRESHOLD = 0.10  # percentage points (i.e. 10 pp)
DEFAULT_P_VALUE_THRESHOLD = 0.05


class DriftDetector:
    def __init__(
        self,
        latency_pct_threshold: float = DEFAULT_LATENCY_PCT_THRESHOLD,
        length_pct_threshold: float = DEFAULT_LENGTH_PCT_THRESHOLD,
        error_rate_delta_threshold: float = DEFAULT_ERROR_RATE_DELTA_THRESHOLD,
        p_value_threshold: float = DEFAULT_P_VALUE_THRESHOLD,
        min_samples_per_window: int = MIN_SAMPLES_PER_WINDOW,
    ) -> None:
        self.latency_pct_threshold = latency_pct_threshold
        self.length_pct_threshold = length_pct_threshold
        self.error_rate_delta_threshold = error_rate_delta_threshold
        self.p_value_threshold = p_value_threshold
        self.min_samples_per_window = min_samples_per_window

    # ------------------------------------------------------------------
    # Public entry
    # ------------------------------------------------------------------

    async def detect(
        self,
        db: AsyncSession,
        model_id,
        current_days: int = 7,
        baseline_days: int = 7,
        now: Optional[datetime] = None,
    ) -> dict:
        if current_days < 1 or baseline_days < 1:
            raise ValueError("current_days and baseline_days must be >= 1")

        now = now or datetime.now(timezone.utc)
        current_from = now - timedelta(days=current_days)
        baseline_to = current_from
        baseline_from = baseline_to - timedelta(days=baseline_days)

        current_rows = await self._fetch_window(db, model_id, current_from, now)
        baseline_rows = await self._fetch_window(db, model_id, baseline_from, baseline_to)

        current_window = self._window_meta(current_from, now, current_rows)
        baseline_window = self._window_meta(baseline_from, baseline_to, baseline_rows)

        if (
            len(current_rows) < self.min_samples_per_window
            or len(baseline_rows) < self.min_samples_per_window
        ):
            return {
                "model_id": str(model_id),
                "current_window": current_window,
                "baseline_window": baseline_window,
                "signals": {},
                "overall_drift": False,
                "insufficient_data": True,
                "min_samples_per_window": self.min_samples_per_window,
            }

        latency = self._compare_latency(baseline_rows, current_rows)
        length = self._compare_length(baseline_rows, current_rows)
        error = self._compare_error_rate(baseline_rows, current_rows)

        overall = any(s["drifted"] for s in (latency, length, error))

        return {
            "model_id": str(model_id),
            "current_window": current_window,
            "baseline_window": baseline_window,
            "signals": {
                "latency": latency,
                "response_length": length,
                "error_rate": error,
            },
            "overall_drift": overall,
            "insufficient_data": False,
        }

    # ------------------------------------------------------------------
    # DB access
    # ------------------------------------------------------------------

    @staticmethod
    async def _fetch_window(
        db: AsyncSession,
        model_id,
        window_from: datetime,
        window_to: datetime,
    ) -> list[AuditLog]:
        rows = (
            await db.execute(
                select(AuditLog)
                .where(
                    AuditLog.model_id == model_id,
                    AuditLog.timestamp >= window_from,
                    AuditLog.timestamp < window_to,
                )
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    def _window_meta(
        window_from: datetime, window_to: datetime, rows: list[AuditLog]
    ) -> dict:
        return {
            "from": window_from.isoformat(),
            "to": window_to.isoformat(),
            "n": len(rows),
        }

    # ------------------------------------------------------------------
    # Signal comparisons
    # ------------------------------------------------------------------

    def _compare_latency(
        self, baseline: list[AuditLog], current: list[AuditLog]
    ) -> dict:
        b = np.asarray([r.latency_ms for r in baseline], dtype=float)
        c = np.asarray([r.latency_ms for r in current], dtype=float)
        b_p95 = float(np.percentile(b, 95))
        c_p95 = float(np.percentile(c, 95))
        pct_change = _pct_change(b_p95, c_p95)
        p_value = _mann_whitney(b, c)
        drifted = (
            abs(pct_change) >= self.latency_pct_threshold
            and p_value is not None
            and p_value < self.p_value_threshold
        )
        return {
            "baseline_p95": b_p95,
            "current_p95": c_p95,
            "baseline_mean": float(np.mean(b)),
            "current_mean": float(np.mean(c)),
            "pct_change": pct_change,
            "p_value": p_value,
            "drifted": drifted,
        }

    def _compare_length(
        self, baseline: list[AuditLog], current: list[AuditLog]
    ) -> dict:
        b = np.asarray([r.completion_tokens for r in baseline], dtype=float)
        c = np.asarray([r.completion_tokens for r in current], dtype=float)
        b_mean = float(np.mean(b))
        c_mean = float(np.mean(c))
        pct_change = _pct_change(b_mean, c_mean)
        p_value = _mann_whitney(b, c)
        drifted = (
            abs(pct_change) >= self.length_pct_threshold
            and p_value is not None
            and p_value < self.p_value_threshold
        )
        return {
            "baseline_mean": b_mean,
            "current_mean": c_mean,
            "pct_change": pct_change,
            "p_value": p_value,
            "drifted": drifted,
        }

    def _compare_error_rate(
        self, baseline: list[AuditLog], current: list[AuditLog]
    ) -> dict:
        b_rate = _error_rate(baseline)
        c_rate = _error_rate(current)
        delta = c_rate - b_rate  # signed, in fraction (0..1)
        drifted = abs(delta) >= self.error_rate_delta_threshold
        return {
            "baseline_rate": b_rate,
            "current_rate": c_rate,
            "delta": delta,
            "drifted": drifted,
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _pct_change(baseline: float, current: float) -> float:
    """Signed percent change vs baseline. Returns 0 when baseline is 0 and
    current is also 0; otherwise +inf-style behaviour is avoided by returning
    100 for a non-zero current against a zero baseline (a "new from zero"
    case that the flag-threshold can still trip on)."""
    if baseline == 0:
        return 0.0 if current == 0 else 100.0
    return ((current - baseline) / baseline) * 100.0


def _mann_whitney(b: np.ndarray, c: np.ndarray) -> Optional[float]:
    """Two-sided Mann-Whitney U on the raw samples. Returns the p-value, or
    None when the test cannot run (e.g. one side is all identical values)."""
    if len(b) == 0 or len(c) == 0:
        return None
    try:
        result = stats.mannwhitneyu(b, c, alternative="two-sided")
        p = float(result.pvalue)
        # Guard against NaN that scipy can return when both arrays are
        # entirely identical constants.
        if np.isnan(p):
            return None
        return p
    except ValueError:
        # scipy raises ValueError if all values are the same across both sides.
        return None


def _error_rate(rows: list[AuditLog]) -> float:
    if not rows:
        return 0.0
    return sum(1 for r in rows if r.status == "error") / len(rows)
