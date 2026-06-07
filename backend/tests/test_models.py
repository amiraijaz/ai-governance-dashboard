"""Model Registry tests."""

import pytest


SAMPLE = {
    "name": "Test Bot",
    "provider": "Anthropic",
    "model_version": "claude-haiku-4-5",
    "risk_level": "Medium",
    "status": "Active",
    "owner_team": "Platform",
    "owner_email": "owner@example.com",
    "use_case": "Used by the test suite.",
    "description": "Created by an integration test.",
}


async def test_unauthenticated_list_is_401(client):
    r = await client.get("/api/models/")
    assert r.status_code == 401


async def test_create_returns_201_and_persists(auth_client):
    r = await auth_client.post("/api/models/", json=SAMPLE)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == SAMPLE["name"]
    assert body["provider"] == SAMPLE["provider"]
    assert body["model_version"] == SAMPLE["model_version"]
    assert body["risk_level"] == "Medium"
    assert body["status"] == "Active"
    assert "id" in body and "created_at" in body and "updated_at" in body


async def test_list_returns_created_and_paginates(auth_client):
    # Seed three rows with distinct names.
    for i in range(3):
        payload = {**SAMPLE, "name": f"Bot {i}", "model_version": f"v{i}"}
        r = await auth_client.post("/api/models/", json=payload)
        assert r.status_code == 201

    # Full page.
    r = await auth_client.get("/api/models/")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3
    assert body["page"] == 1
    assert body["pages"] == 1
    names = {item["name"] for item in body["items"]}
    assert names == {"Bot 0", "Bot 1", "Bot 2"}

    # Paginate at limit=2.
    r = await auth_client.get("/api/models/?page=1&limit=2")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["pages"] == 2

    r = await auth_client.get("/api/models/?page=2&limit=2")
    assert len(r.json()["items"]) == 1


async def test_get_by_id(auth_client):
    created = (await auth_client.post("/api/models/", json=SAMPLE)).json()
    r = await auth_client.get(f"/api/models/{created['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]


async def test_get_unknown_id_is_404(auth_client):
    r = await auth_client.get("/api/models/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


async def test_patch_updates_fields(auth_client):
    created = (await auth_client.post("/api/models/", json=SAMPLE)).json()
    r = await auth_client.patch(
        f"/api/models/{created['id']}",
        json={"risk_level": "Critical", "status": "Paused"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["risk_level"] == "Critical"
    assert body["status"] == "Paused"
    # Untouched field stays.
    assert body["provider"] == SAMPLE["provider"]


async def test_delete_is_a_hard_delete(auth_client):
    """The current DELETE endpoint hard-deletes (db.delete + commit). This
    test pins that real behavior — if the endpoint is changed to a soft
    archive (set status=Archived), this test must be updated alongside the
    router change."""
    created = (await auth_client.post("/api/models/", json=SAMPLE)).json()
    r = await auth_client.delete(f"/api/models/{created['id']}")
    assert r.status_code == 204
    # Row is gone.
    after = await auth_client.get(f"/api/models/{created['id']}")
    assert after.status_code == 404


@pytest.mark.xfail(
    reason="GET /api/models/ does not currently accept provider/risk_level/status "
    "filter query params — the router signature only has page + limit. This "
    "test is left xfail so the gap is visible in CI rather than hidden."
)
async def test_list_filters_by_provider_risk_status(auth_client):
    await auth_client.post(
        "/api/models/",
        json={**SAMPLE, "name": "OpenAI bot", "provider": "OpenAI", "risk_level": "Low"},
    )
    await auth_client.post(
        "/api/models/",
        json={**SAMPLE, "name": "Anthropic bot", "provider": "Anthropic", "risk_level": "Critical"},
    )
    r = await auth_client.get("/api/models/?provider=OpenAI")
    assert r.status_code == 200
    assert all(m["provider"] == "OpenAI" for m in r.json()["items"])
