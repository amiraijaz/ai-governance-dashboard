"""Pricing endpoint tests.

The /sync endpoint is admin-only; /list and /update require a logged-in
user. The autouse mock in conftest already stubs pricing_sync_service.sync_all
to a fake SyncSummary so the admin sync test doesn't fetch LiteLLM.
"""

import pytest


async def test_list_returns_seeded_rows(auth_client, seeded_pricing):
    r = await auth_client.get("/api/pricing/")
    assert r.status_code == 200, r.text
    rows = r.json()
    # seeded_pricing inserts four rows.
    assert len(rows) == 4
    keys = {row["model_key"] for row in rows}
    assert keys == {
        "claude-haiku-4-5",
        "claude-sonnet-4-5",
        "gpt-4o",
        "gpt-4o-mini",
    }
    # Every row should have a numeric cost (returned as string in JSON
    # because of Decimal — Pydantic serialises Decimal to string by default).
    for row in rows:
        # Either string or float — both are valid JSON serialisations of Decimal.
        assert "prompt_cost_per_1k" in row
        assert "completion_cost_per_1k" in row


async def test_list_filters_by_provider(auth_client, seeded_pricing):
    r = await auth_client.get("/api/pricing/?provider=OpenAI")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert all(row["provider"] == "OpenAI" for row in rows)


async def test_sync_as_non_admin_is_403(auth_client):
    """auth_client is a freshly-registered viewer. require_admin must reject."""
    r = await auth_client.post("/api/pricing/sync")
    assert r.status_code == 403


async def test_sync_as_admin_returns_summary(admin_client, seeded_pricing):
    """The autouse mock makes sync_all return SyncSummary(synced=0, updated=0,
    errors=[]) so this never hits the network."""
    r = await admin_client.post("/api/pricing/sync")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"synced", "updated", "errors"}
    assert body["synced"] == 0
    assert body["updated"] == 0
    assert body["errors"] == []


async def test_sync_unauthenticated_is_401(client):
    r = await client.post("/api/pricing/sync")
    assert r.status_code == 401


async def test_update_changes_costs(auth_client, seeded_pricing):
    # Pick gpt-4o-mini, bump its prompt cost.
    rows = (await auth_client.get("/api/pricing/?provider=OpenAI")).json()
    target = next(r for r in rows if r["model_key"] == "gpt-4o-mini")

    r = await auth_client.put(
        f"/api/pricing/{target['id']}",
        json={"prompt_cost_per_1k": "0.0002", "is_active": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # JSON-decoded Decimal — accept either repr.
    assert pytest.approx(float(body["prompt_cost_per_1k"]), rel=1e-9) == 0.0002


async def test_update_nonexistent_pricing_is_404(auth_client):
    import uuid
    r = await auth_client.put(
        f"/api/pricing/{uuid.uuid4()}",
        json={"prompt_cost_per_1k": "0.1"},
    )
    assert r.status_code == 404
