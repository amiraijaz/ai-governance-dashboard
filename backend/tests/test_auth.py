"""Auth surface tests — covers register, login, refresh, /me, and the
load-bearing security invariant that /auth/register never lets a caller
self-promote to admin."""

import pytest


PASSWORD = "TestPass123!"


async def test_register_returns_viewer(client):
    r = await client.post(
        "/api/auth/register",
        json={"email": "alice@example.com", "password": PASSWORD, "organisation": "Acme"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "alice@example.com"
    assert body["role"] == "viewer"
    assert body["organisation"] == "Acme"
    assert "id" in body and "created_at" in body


async def test_register_cannot_self_promote_to_admin(client):
    """The register schema (RegisterRequest) has no `role` field; pydantic
    drops the extra and the handler hard-codes role=viewer. This test guards
    against a future regression that adds `role` to the schema by accident."""
    r = await client.post(
        "/api/auth/register",
        json={
            "email": "evil@example.com",
            "password": PASSWORD,
            "role": "admin",  # extra field
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "viewer"


async def test_register_duplicate_email_is_409(client):
    payload = {"email": "dup@example.com", "password": PASSWORD}
    first = await client.post("/api/auth/register", json=payload)
    assert first.status_code == 201
    again = await client.post("/api/auth/register", json=payload)
    assert again.status_code == 409


async def test_login_success_returns_token_pair(client):
    await client.post(
        "/api/auth/register",
        json={"email": "bob@example.com", "password": PASSWORD},
    )
    r = await client.post(
        "/api/auth/login",
        json={"email": "bob@example.com", "password": PASSWORD},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str) and len(body["access_token"]) > 20
    assert isinstance(body["refresh_token"], str) and len(body["refresh_token"]) > 20
    assert body["expires_in"] > 0


async def test_login_wrong_password_is_401(client):
    await client.post(
        "/api/auth/register",
        json={"email": "carol@example.com", "password": PASSWORD},
    )
    r = await client.post(
        "/api/auth/login",
        json={"email": "carol@example.com", "password": "WrongPass1!"},
    )
    assert r.status_code == 401


async def test_login_unknown_email_is_401(client):
    r = await client.post(
        "/api/auth/login",
        json={"email": "ghost@example.com", "password": PASSWORD},
    )
    assert r.status_code == 401


async def test_me_with_valid_token_returns_user(auth_client):
    r = await auth_client.get("/api/auth/me")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == auth_client.test_user_email
    assert body["role"] == "viewer"


async def test_me_without_token_is_401(client):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


async def test_me_with_bad_token_is_401(client):
    client.headers["Authorization"] = "Bearer not.a.real.jwt"
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


async def test_refresh_returns_new_access_token(client):
    await client.post(
        "/api/auth/register",
        json={"email": "dan@example.com", "password": PASSWORD},
    )
    login = await client.post(
        "/api/auth/login",
        json={"email": "dan@example.com", "password": PASSWORD},
    )
    refresh_token = login.json()["refresh_token"]

    r = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "access_token" in body
    assert "refresh_token" in body
    # The new access token decodes back to a usable session — prove it by
    # calling /me with it.
    client.headers["Authorization"] = f"Bearer {body['access_token']}"
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "dan@example.com"


async def test_refresh_with_garbage_is_401(client):
    r = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": "not-a-real-token"},
    )
    assert r.status_code == 401


@pytest.mark.skip(
    reason="slowapi limiter is disabled in tests (would require live Redis "
    "and many real bcrypt-hashed registrations). Limit itself is "
    "exercised in production; covered by integration smoke."
)
async def test_register_rate_limit_eventually_429(client):
    # Kept as documentation. Re-enable when we have a Redis-backed integration
    # tier that's willing to spend the bcrypt cycles for 6 sequential registers.
    pass
