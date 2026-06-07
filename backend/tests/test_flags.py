"""Safety flag review-queue tests."""

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Seed helper — creates a model + a few logs + their flags.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_flags(auth_client, db_session):
    """Create one model and a deterministic mix of safety flags.

    Layout: 3 RED, 2 YELLOW, 1 GREEN. Two RED flags are pre-reviewed.
    """
    from models import AuditLog, ModelRegistry, SafetyFlag

    # Reuse the auth_client's session via the dependency override — it's the
    # same db_session under the hood. Create the model directly.
    model = ModelRegistry(
        name="Flag target",
        provider="Anthropic",
        model_version="claude-haiku-4-5",
        risk_level="High",
        status="Active",
    )
    db_session.add(model)
    await db_session.commit()
    await db_session.refresh(model)

    now = datetime.now(timezone.utc)

    flags_to_make = [
        ("RED",    False, None),
        ("RED",    True,  "issue_found"),
        ("RED",    True,  "escalated"),
        ("YELLOW", False, None),
        ("YELLOW", False, None),
        ("GREEN",  False, None),
    ]
    created_ids: list[uuid.UUID] = []
    for sev, reviewed, status in flags_to_make:
        log = AuditLog(
            model_id=model.id,
            prompt_tokens=10,
            completion_tokens=10,
            total_cost_usd=0.0001,
            latency_ms=500,
            status="success",
            flagged=True,
            flag_severity=sev,
        )
        db_session.add(log)
        await db_session.flush()

        flag = SafetyFlag(
            log_id=log.id,
            model_id=model.id,
            flag_type="PII_DETECTED" if sev == "RED" else "PROMPT_INJECTION",
            severity=sev,
            confidence=0.9 if sev == "RED" else 0.7,
            reviewed=reviewed,
            reviewed_at=now if reviewed else None,
            review_status=status,
        )
        db_session.add(flag)
        await db_session.flush()
        created_ids.append(flag.id)

    await db_session.commit()
    return {"model_id": model.id, "flag_ids": created_ids}


# ---------------------------------------------------------------------------
# /stats
# ---------------------------------------------------------------------------


async def test_stats_returns_counts(auth_client, seeded_flags):
    r = await auth_client.get("/api/flags/stats")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 6
    assert body["red"] == 3
    assert body["yellow"] == 2
    assert body["green"] == 1
    # 2 pre-reviewed → 4 open.
    assert body["open"] == 4


async def test_stats_route_not_shadowed_by_id_route(auth_client):
    """If /stats were registered AFTER /{flag_id}, FastAPI would try to
    parse 'stats' as a UUID and 422. This test pins the route order."""
    r = await auth_client.get("/api/flags/stats")
    assert r.status_code == 200
    # 422 here would mean 'stats' fell through to /{flag_id}.
    assert "total" in r.json()


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


async def test_filter_by_severity(auth_client, seeded_flags):
    r = await auth_client.get("/api/flags/?severity=RED")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert all(item["severity"] == "RED" for item in body["items"])


async def test_filter_by_reviewed(auth_client, seeded_flags):
    r = await auth_client.get("/api/flags/?reviewed=false")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    assert all(item["reviewed"] is False for item in body["items"])


# ---------------------------------------------------------------------------
# Review action
# ---------------------------------------------------------------------------


async def test_review_marks_flag_and_records_reviewer(auth_client, seeded_flags):
    # Pick the first open flag.
    open_resp = await auth_client.get("/api/flags/?reviewed=false&limit=1")
    open_id = open_resp.json()["items"][0]["id"]

    r = await auth_client.put(
        f"/api/flags/{open_id}/review",
        json={"review_status": "safe", "review_notes": "False positive."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reviewed"] is True
    assert body["review_status"] == "safe"
    assert body["review_notes"] == "False positive."
    assert body["reviewed_by"] == auth_client.test_user_email
    assert body["reviewed_at"] is not None


async def test_review_with_invalid_status_is_422(auth_client, seeded_flags):
    open_resp = await auth_client.get("/api/flags/?reviewed=false&limit=1")
    open_id = open_resp.json()["items"][0]["id"]

    r = await auth_client.put(
        f"/api/flags/{open_id}/review",
        json={"review_status": "definitely_a_problem", "review_notes": ""},
    )
    assert r.status_code == 422


async def test_review_nonexistent_flag_is_404(auth_client):
    r = await auth_client.put(
        f"/api/flags/{uuid.uuid4()}/review",
        json={"review_status": "safe"},
    )
    assert r.status_code == 404
