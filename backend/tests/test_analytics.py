"""Analytics endpoint tests.

Seeds a small but deterministic dataset (one model, a handful of logs of
known cost + latency) and checks the summary / cost / requests / latency /
models endpoints return data of the right shape and pass basic sanity.
"""

from datetime import datetime, timedelta, timezone

import pytest_asyncio


@pytest_asyncio.fixture
async def seeded_logs(auth_client, db_session):
    """One model + 5 logs spread across the last few days."""
    from models import AuditLog, ModelRegistry

    model = ModelRegistry(
        name="Analytics target",
        provider="Anthropic",
        model_version="claude-haiku-4-5",
        risk_level="Medium",
        status="Active",
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)

    now = datetime.now(timezone.utc)
    rows = [
        # (offset_days, prompt_tokens, completion_tokens, cost, latency_ms, status, flagged)
        (0, 1000, 500, 0.0028, 800,  "success", False),
        (1, 2000, 800, 0.0048, 1200, "success", False),
        (2, 500,  200, 0.0014, 600,  "success", True),
        (3, 100,  0,   0.0001, 100,  "error",   False),
        (5, 3000, 1500, 0.0072, 1500, "success", False),
    ]
    for offset, ptok, ctok, cost, lat, status, flagged in rows:
        db_session.add(
            AuditLog(
                model_id=model.id,
                timestamp=now - timedelta(days=offset),
                prompt_tokens=ptok,
                completion_tokens=ctok,
                total_cost_usd=cost,
                latency_ms=lat,
                status=status,
                flagged=flagged,
                flag_severity="YELLOW" if flagged else None,
            )
        )
    await db_session.commit()
    return model


# ---------------------------------------------------------------------------
# /summary — the dashboard-driving endpoint
# ---------------------------------------------------------------------------


async def test_summary_returns_full_shape(auth_client, seeded_logs):
    r = await auth_client.get("/api/analytics/summary")
    assert r.status_code == 200, r.text
    body = r.json()

    # Top-level scalars.
    assert body["models_registered"] == 1
    assert body["calls_this_month"] >= 0          # may include older rows
    assert isinstance(body["cost_this_month"], float)
    assert isinstance(body["open_flags"], int)

    # Card-specific structures we added in the dashboard redesign.
    risk = body["models_by_risk"]
    assert set(risk.keys()) == {"low", "medium", "high", "critical", "added_this_month"}
    assert risk["medium"] == 1                    # the only seeded model

    drivers = body["top_cost_models"]
    assert isinstance(drivers, list)
    assert len(drivers) >= 1
    assert drivers[0]["name"] == "Analytics target"
    assert 0 <= drivers[0]["share_pct"] <= 100

    sev = body["open_flags_by_severity"]
    assert set(sev.keys()) == {"red", "yellow", "green"}

    for delta_key in ("calls_delta", "cost_delta", "flags_delta"):
        delta = body[delta_key]
        assert set(delta.keys()) == {"current", "previous", "pct_change"}
        assert isinstance(delta["current"], (int, float))
        # pct_change is None when the prior window was empty.
        assert delta["pct_change"] is None or isinstance(delta["pct_change"], (int, float))


async def test_summary_cost_sparkline_present(auth_client, seeded_logs):
    body = (await auth_client.get("/api/analytics/summary")).json()
    spark = body["cost_last_30_days"]
    assert isinstance(spark, list)
    # At least the seeded days should show up.
    assert len(spark) >= 1
    for point in spark:
        assert set(point.keys()) >= {"date", "cost"}


# ---------------------------------------------------------------------------
# /cost, /requests, /latency
# ---------------------------------------------------------------------------


async def test_cost_endpoint_returns_data(auth_client, seeded_logs):
    r = await auth_client.get("/api/analytics/cost?period=30d&group_by=day")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list) and len(rows) >= 1
    for row in rows:
        assert "label" in row
        assert "total_cost_usd" in row
        assert "request_count" in row


async def test_requests_endpoint_returns_data(auth_client, seeded_logs):
    r = await auth_client.get("/api/analytics/requests?period=30d")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list) and len(rows) >= 1
    # The error row should bump error_count somewhere in the series.
    total_errors = sum(row["error_count"] for row in rows)
    total_flagged = sum(row["flagged_count"] for row in rows)
    assert total_errors >= 1
    assert total_flagged >= 1


async def test_latency_endpoint_computes_percentiles(auth_client, seeded_logs):
    """p95/p99 should compute without divide-by-zero or null casts."""
    r = await auth_client.get("/api/analytics/latency?period=30d")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert isinstance(rows, list) and len(rows) >= 1
    for row in rows:
        assert row["avg_latency_ms"] >= 0
        assert row["p95_latency_ms"] >= row["avg_latency_ms"]
        assert row["p99_latency_ms"] >= row["p95_latency_ms"]


async def test_models_breakdown(auth_client, seeded_logs):
    r = await auth_client.get("/api/analytics/models")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    only = rows[0]
    assert only["model_name"] == "Analytics target"
    assert only["total_calls"] == 5
    assert only["total_tokens"] > 0
    assert only["total_cost_usd"] > 0
