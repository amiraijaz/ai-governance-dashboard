"""API key tests — the create-once-display-once contract is the security
invariant here. The raw key MUST appear in the create response and MUST NOT
appear in the list response."""


async def test_unauthenticated_list_is_401(client):
    r = await client.get("/api/keys/")
    assert r.status_code == 401


async def test_create_returns_raw_key_once(auth_client):
    r = await auth_client.post("/api/keys/", json={"name": "deploy bot"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert "key" in body
    assert isinstance(body["key"], str)
    assert len(body["key"]) >= 32                      # 32 bytes hex = 64 chars
    assert body["name"] == "deploy bot"
    assert body["is_active"] is True
    assert "key_hash" not in body                       # never leak the hash


async def test_list_omits_raw_key_and_hash(auth_client):
    create = await auth_client.post("/api/keys/", json={"name": "ci bot"})
    raw_key = create.json()["key"]

    r = await auth_client.get("/api/keys/")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    info = items[0]

    # Metadata is present.
    assert info["name"] == "ci bot"
    assert info["is_active"] is True
    assert "created_at" in info

    # Neither the raw key nor its hash leaks on list.
    assert "key" not in info
    assert "key_hash" not in info

    # And to be totally explicit, the raw key text isn't anywhere in the body.
    assert raw_key not in r.text


async def test_create_returns_unique_key_each_time(auth_client):
    a = (await auth_client.post("/api/keys/", json={"name": "a"})).json()["key"]
    b = (await auth_client.post("/api/keys/", json={"name": "b"})).json()["key"]
    assert a != b


async def test_delete_is_soft_sets_is_active_false(auth_client):
    create = await auth_client.post("/api/keys/", json={"name": "throwaway"})
    key_id = create.json()["id"]

    r = await auth_client.delete(f"/api/keys/{key_id}")
    assert r.status_code == 204

    r = await auth_client.get("/api/keys/")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1                              # row still present
    assert items[0]["id"] == key_id
    assert items[0]["is_active"] is False               # but deactivated


async def test_delete_other_users_key_is_404(client, auth_client):
    """A second user cannot delete the first user's key (404, not 403,
    because we don't want to confirm key existence to non-owners)."""
    first_key_id = (await auth_client.post("/api/keys/", json={"name": "mine"})).json()["id"]

    # Build a fresh second user. Reuse the un-headered `client` and override
    # the Authorization header for the second login.
    await client.post(
        "/api/auth/register",
        json={"email": "other@example.com", "password": "TestPass123!"},
    )
    login = await client.post(
        "/api/auth/login",
        json={"email": "other@example.com", "password": "TestPass123!"},
    )
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

    r = await client.delete(f"/api/keys/{first_key_id}")
    assert r.status_code == 404
