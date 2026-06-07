"""Drift detector tests.

Each test seeds two AuditLog windows (baseline + current) for a single model
and asserts the right signal flips. The RNG is seeded so the statistical
tests are deterministic across runs.
"""

import random
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from models import AuditLog, ModelRegistry
from services.evaluators import DriftDetector


# Use a fixed "now" inside the tests so window boundaries are deterministic.
FAKE_NOW = datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


async def _make_model(db_session) -> ModelRegistry:
    m = ModelRegistry(
        name="Drift target",
        provider="Anthropic",
        model_version="claude-haiku-4-5",
        risk_level="Medium",
        status="Active",
    )
    db_session.add(m)
    await db_session.commit()
    await db_session.refresh(m)
    return m


def _ts_in(window_from: datetime, window_to: datetime, rng: random.Random) -> datetime:
    """A timestamp uniformly sampled inside the window (strictly inside, so
    a row scheduled at the exact `to` boundary does not slip into the next
    window — the detector uses `< window_to`)."""
    span = (window_to - window_from).total_seconds()
    return window_from + timedelta(seconds=rng.uniform(0, span - 1))


async def _seed_window(
    db_session,
    model_id,
    window_from: datetime,
    window_to: datetime,
    latencies_ms: list[int],
    completion_tokens: list[int],
    statuses: list[str],
) -> None:
    """Insert one log per index of the three parallel arrays."""
    rng = random.Random(42)
    n = len(latencies_ms)
    assert len(completion_tokens) == n == len(statuses)
    for lat, tok, st in zip(latencies_ms, completion_tokens, statuses):
        db_session.add(
            AuditLog(
                model_id=model_id,
                timestamp=_ts_in(window_from, window_to, rng),
                prompt_tokens=100,
                completion_tokens=tok,
                total_cost_usd=0.0001,
                latency_ms=lat,
                status=st,
            )
        )
    await db_session.commit()


@pytest_asyncio.fixture
async def model_id(db_session):
    m = await _make_model(db_session)
    return m.id


# Default window boundaries used by most tests: 7-day current, 7-day baseline.
CURRENT_FROM = FAKE_NOW - timedelta(days=7)
BASELINE_FROM = FAKE_NOW - timedelta(days=14)
BASELINE_TO = CURRENT_FROM


# ---------------------------------------------------------------------------
# Latency drift
# ---------------------------------------------------------------------------


async def test_clear_latency_drift_is_flagged(db_session, model_id):
    """Baseline ~500ms, current ~2000ms → both conditions hit."""
    rng = random.Random(1)
    baseline_lat = [int(rng.gauss(500, 50)) for _ in range(40)]
    current_lat = [int(rng.gauss(2000, 200)) for _ in range(40)]
    common_tok = [200] * 40
    common_status = ["success"] * 40

    await _seed_window(
        db_session, model_id, BASELINE_FROM, BASELINE_TO,
        baseline_lat, common_tok, common_status,
    )
    await _seed_window(
        db_session, model_id, CURRENT_FROM, FAKE_NOW,
        current_lat, common_tok, common_status,
    )

    out = await DriftDetector().detect(db_session, model_id, now=FAKE_NOW)

    assert out["insufficient_data"] is False
    assert out["current_window"]["n"] == 40
    assert out["baseline_window"]["n"] == 40
    lat = out["signals"]["latency"]
    assert lat["pct_change"] > 100              # ~300% shift
    assert lat["p_value"] is not None and lat["p_value"] < 0.05
    assert lat["drifted"] is True
    # Length and error rate didn't change → not flagged.
    assert out["signals"]["response_length"]["drifted"] is False
    assert out["signals"]["error_rate"]["drifted"] is False
    assert out["overall_drift"] is True


async def test_identical_distributions_not_flagged(db_session, model_id):
    """Same lognormal both sides → no signal trips."""
    rng = random.Random(7)
    lat_b = [int(rng.gauss(800, 100)) for _ in range(40)]
    lat_c = [int(rng.gauss(800, 100)) for _ in range(40)]
    tok_b = [200] * 40
    tok_c = [200] * 40
    st = ["success"] * 40

    await _seed_window(db_session, model_id, BASELINE_FROM, BASELINE_TO, lat_b, tok_b, st)
    await _seed_window(db_session, model_id, CURRENT_FROM, FAKE_NOW, lat_c, tok_c, st)

    out = await DriftDetector().detect(db_session, model_id, now=FAKE_NOW)
    assert out["insufficient_data"] is False
    assert out["overall_drift"] is False
    assert out["signals"]["latency"]["drifted"] is False
    assert out["signals"]["response_length"]["drifted"] is False
    assert out["signals"]["error_rate"]["drifted"] is False


# ---------------------------------------------------------------------------
# Both-conditions rule
# ---------------------------------------------------------------------------


async def test_tiny_but_significant_shift_not_flagged(db_session, model_id):
    """Construct a shift that's statistically significant (large N, low
    variance) but small in effect size (under 25%). The both-conditions
    rule must keep this OUT of the drifted set."""
    # 200 samples each side, baseline mean 1000, current mean 1100 (+10%).
    # Variance is tiny so MW-U almost certainly says p < 0.05, but the
    # 10% effect is below the 25% threshold.
    rng = random.Random(13)
    lat_b = [int(rng.gauss(1000, 5)) for _ in range(200)]
    lat_c = [int(rng.gauss(1100, 5)) for _ in range(200)]
    tok = [200] * 200
    st = ["success"] * 200

    await _seed_window(db_session, model_id, BASELINE_FROM, BASELINE_TO, lat_b, tok, st)
    await _seed_window(db_session, model_id, CURRENT_FROM, FAKE_NOW, lat_c, tok, st)

    out = await DriftDetector().detect(db_session, model_id, now=FAKE_NOW)
    lat = out["signals"]["latency"]

    # Statistically significant…
    assert lat["p_value"] is not None and lat["p_value"] < 0.05
    # …but the effect size is small.
    assert abs(lat["pct_change"]) < 25
    # The both-conditions rule keeps drifted=False.
    assert lat["drifted"] is False
    assert out["overall_drift"] is False


# ---------------------------------------------------------------------------
# Insufficient data
# ---------------------------------------------------------------------------


async def test_insufficient_data_short_circuits(db_session, model_id):
    """Current window with 5 logs → return insufficient_data=True, no stats."""
    rng = random.Random(3)
    # Baseline has plenty, current is starved.
    lat_b = [int(rng.gauss(500, 50)) for _ in range(40)]
    lat_c = [int(rng.gauss(2000, 200)) for _ in range(5)]
    await _seed_window(
        db_session, model_id, BASELINE_FROM, BASELINE_TO,
        lat_b, [200] * 40, ["success"] * 40,
    )
    await _seed_window(
        db_session, model_id, CURRENT_FROM, FAKE_NOW,
        lat_c, [200] * 5, ["success"] * 5,
    )

    out = await DriftDetector().detect(db_session, model_id, now=FAKE_NOW)
    assert out["insufficient_data"] is True
    assert out["overall_drift"] is False
    assert out["current_window"]["n"] == 5
    assert out["baseline_window"]["n"] == 40
    # Signals are omitted, not zero — caller should branch on insufficient_data.
    assert out["signals"] == {}


# ---------------------------------------------------------------------------
# Error rate drift
# ---------------------------------------------------------------------------


async def test_error_rate_shift_is_flagged(db_session, model_id):
    """Baseline 5% errors → current 30% errors → 25pp shift, well above 10pp."""
    n = 40
    baseline_statuses = ["error" if i < 2 else "success" for i in range(n)]   # 5%
    current_statuses = ["error" if i < 12 else "success" for i in range(n)]   # 30%
    common_lat = [800] * n
    common_tok = [200] * n

    await _seed_window(db_session, model_id, BASELINE_FROM, BASELINE_TO,
                       common_lat, common_tok, baseline_statuses)
    await _seed_window(db_session, model_id, CURRENT_FROM, FAKE_NOW,
                       common_lat, common_tok, current_statuses)

    out = await DriftDetector().detect(db_session, model_id, now=FAKE_NOW)
    err = out["signals"]["error_rate"]
    assert err["baseline_rate"] == pytest.approx(0.05)
    assert err["current_rate"] == pytest.approx(0.30)
    assert err["delta"] == pytest.approx(0.25)
    assert err["drifted"] is True
    assert out["overall_drift"] is True


async def test_error_rate_small_shift_not_flagged(db_session, model_id):
    """3pp shift in error rate is under the 10pp default → not flagged."""
    n = 40
    baseline_statuses = ["error" if i < 2 else "success" for i in range(n)]   # 5%
    current_statuses = ["error" if i < 3 else "success" for i in range(n)]    # 7.5%
    common_lat = [800] * n
    common_tok = [200] * n

    await _seed_window(db_session, model_id, BASELINE_FROM, BASELINE_TO,
                       common_lat, common_tok, baseline_statuses)
    await _seed_window(db_session, model_id, CURRENT_FROM, FAKE_NOW,
                       common_lat, common_tok, current_statuses)

    out = await DriftDetector().detect(db_session, model_id, now=FAKE_NOW)
    err = out["signals"]["error_rate"]
    assert err["drifted"] is False


# ---------------------------------------------------------------------------
# Other model rows must not pollute the comparison
# ---------------------------------------------------------------------------


async def test_other_models_logs_are_ignored(db_session, model_id):
    """Logs belonging to a different model in the same window must not
    leak into the detector's sample."""
    rng = random.Random(99)

    # Target model — small clean signal, no drift.
    await _seed_window(
        db_session, model_id, BASELINE_FROM, BASELINE_TO,
        [int(rng.gauss(500, 30)) for _ in range(20)], [200] * 20, ["success"] * 20,
    )
    await _seed_window(
        db_session, model_id, CURRENT_FROM, FAKE_NOW,
        [int(rng.gauss(500, 30)) for _ in range(20)], [200] * 20, ["success"] * 20,
    )

    # Noise model — wild latency, would absolutely flag if it leaked in.
    other = ModelRegistry(
        name="Noise model", provider="OpenAI", model_version="gpt-4o-mini",
        risk_level="Low", status="Active",
    )
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    await _seed_window(
        db_session, other.id, CURRENT_FROM, FAKE_NOW,
        [int(rng.gauss(5000, 500)) for _ in range(40)], [800] * 40, ["error"] * 40,
    )

    out = await DriftDetector().detect(db_session, model_id, now=FAKE_NOW)
    assert out["current_window"]["n"] == 20      # target model only
    assert out["overall_drift"] is False
