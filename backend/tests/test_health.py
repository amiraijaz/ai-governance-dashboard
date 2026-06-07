"""Health endpoint — open (no auth) and always returns 200 with a
structured body so monitors can parse `services.*` to decide what's wrong.
"""


async def test_health_returns_structured_body(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    # Top-level shape pinned so a "small" change to the response can't
    # silently break load balancer probes that parse it.
    assert set(body.keys()) >= {"status", "timestamp", "services", "version"}
    assert body["status"] in ("ok", "degraded")
    services = body["services"]
    assert set(services.keys()) == {"database", "redis", "pricing_sync"}
    assert services["database"] in ("up", "down")
    assert services["redis"] in ("up", "down")
    assert services["pricing_sync"] in ("fresh", "stale")


async def test_health_is_unauthenticated(client):
    """Load balancers can't authenticate — the route must accept no header."""
    # Note: the `client` fixture has no Authorization header by default.
    r = await client.get("/health")
    assert r.status_code == 200
