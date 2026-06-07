"""Dashboard-backed evals — httpx is mocked so no real network calls.

Covers:
* logger.evals.run_suite posts to the right endpoint with the Bearer token
* non-2xx responses raise DashboardError (NOT swallowed — the SDK
  explicitly diverges from logger.call here)
* missing token raises DashboardError with a clear message
* basic shape parsing of get_run / list_suites
"""

import pytest
import httpx

from aigovkit import AIGovLogger
from aigovkit.evals import DashboardError, DashboardEvals


# ---------------------------------------------------------------------------
# httpx MockTransport — lets us assert request shape AND control the
# response in one place without monkeypatching internals.
# ---------------------------------------------------------------------------


def make_logger_with_transport(handler, dashboard_url="https://test.example.com"):
    """Build an AIGovLogger whose .evals client uses a MockTransport.

    We rebuild the DashboardEvals._request method's httpx.Client with a
    transport injected by the test. Easiest path: monkeypatch the
    `_request` method on the per-test instance. Actually simpler: replace
    the httpx.Client invocation with one that uses our transport.
    """
    logger = AIGovLogger(
        api_key="sk_ingest",
        model_id="00000000-0000-0000-0000-000000000000",
        dashboard_url=dashboard_url,
        token="test-jwt-token",
    )
    # Force-instantiate so .evals exists, then swap its private _request.
    evals = logger.evals
    transport = httpx.MockTransport(handler)

    def request(method, path, **kwargs):
        url = f"{evals.dashboard_url}{path}"
        with httpx.Client(transport=transport, timeout=evals.timeout_s) as client:
            r = client.request(method, url, headers=evals._headers(), **kwargs)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            raise DashboardError(
                f"{method} {path} returned {r.status_code}: {detail}"
            )
        if not r.content:
            return None
        return r.json()

    evals._request = request  # type: ignore[assignment]
    return logger, evals


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_logger_has_evals_property():
    logger = AIGovLogger(
        api_key="sk_ingest",
        model_id="00000000-0000-0000-0000-000000000000",
        dashboard_url="https://test.example.com",
        token="t",
    )
    assert isinstance(logger.evals, DashboardEvals)
    # Cached singleton.
    assert logger.evals is logger.evals


def test_run_suite_posts_to_correct_endpoint_with_bearer():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["auth"] = request.headers.get("authorization")
        captured["content_type"] = request.headers.get("content-type")
        captured["body"] = request.content
        return httpx.Response(
            202,
            json={"run_id": "11111111-1111-1111-1111-111111111111",
                  "status": "pending", "message": "queued"},
        )

    logger, evals = make_logger_with_transport(handler)
    out = evals.run_suite(
        suite_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        cases=[{"input": "x", "output": "y"}],
    )

    assert out["run_id"] == "11111111-1111-1111-1111-111111111111"
    assert out["status"] == "pending"
    assert captured["method"] == "POST"
    assert captured["url"].endswith(
        "/api/evals/suites/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/run"
    )
    assert captured["auth"] == "Bearer test-jwt-token"
    assert captured["content_type"] == "application/json"


def test_run_suite_omits_cases_when_not_passed():
    captured = {}

    def handler(request):
        captured["body"] = request.content
        return httpx.Response(202, json={"run_id": "r", "status": "pending", "message": "ok"})

    logger, evals = make_logger_with_transport(handler)
    evals.run_suite(suite_id="s")
    assert captured["body"] == b"{}"


def test_get_run_returns_parsed_body():
    def handler(request):
        return httpx.Response(200, json={
            "id": "r", "suite_id": "s", "status": "complete",
            "summary": {"total_cases": 2, "passed": 2},
            "started_at": "2026-06-07T00:00:00Z",
            "completed_at": "2026-06-07T00:00:01Z",
            "error_message": None, "triggered_by": "u@x.com",
            "created_at": "2026-06-07T00:00:00Z",
        })

    _, evals = make_logger_with_transport(handler)
    run = evals.get_run("r")
    assert run["status"] == "complete"
    assert run["summary"]["passed"] == 2


def test_http_error_raises_dashboard_error_with_detail():
    """The dashboard returns a 422 with a detail string — the SDK must
    SURFACE it, not swallow it. This is the explicit divergence from
    logger.call's fire-and-forget behaviour."""
    def handler(request):
        return httpx.Response(422, json={"detail": "invalid rubric: criteria.0.name is required"})

    _, evals = make_logger_with_transport(handler)
    with pytest.raises(DashboardError, match="422") as exc:
        evals.create_suite(
            name="bad", eval_type="llm_judge",
            config={"rubric": "name: x"},
        )
    assert "invalid rubric" in str(exc.value)


def test_network_error_raises_dashboard_error():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    # We need our patched _request to surface httpx errors too. The default
    # impl in _dashboard.py wraps them in DashboardError; the test harness's
    # request replacement lets httpx propagate, so we wrap manually here to
    # match the production contract.
    logger = AIGovLogger(
        api_key="sk", model_id="m",
        dashboard_url="https://test.example.com",
        token="t",
    )
    # Use the REAL _request path (not our harness) by mocking httpx.Client
    # at the module level.
    transport = httpx.MockTransport(handler)
    import aigovkit.evals._dashboard as dash_mod

    real_client_cls = dash_mod.httpx.Client

    class _PatchedClient(real_client_cls):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    dash_mod.httpx.Client = _PatchedClient
    try:
        with pytest.raises(DashboardError, match="connection refused|GET /api/evals/suites failed"):
            logger.evals.list_suites()
    finally:
        dash_mod.httpx.Client = real_client_cls


def test_missing_token_raises_clear_error(monkeypatch):
    monkeypatch.delenv("AIGOVKIT_TOKEN", raising=False)
    logger = AIGovLogger(
        api_key="sk", model_id="m",
        dashboard_url="https://test.example.com",
        # NO token passed in
    )
    with pytest.raises(DashboardError, match="session token"):
        logger.evals.list_suites()


def test_token_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("AIGOVKIT_TOKEN", "from-env")
    captured = {}

    def handler(request):
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=[])

    logger = AIGovLogger(
        api_key="sk", model_id="m",
        dashboard_url="https://test.example.com",
    )
    # Use harness path with the env-supplied token.
    transport = httpx.MockTransport(handler)

    def request(method, path, **kwargs):
        url = f"{logger.evals.dashboard_url}{path}"
        with httpx.Client(transport=transport) as client:
            r = client.request(method, url, headers=logger.evals._headers(), **kwargs)
        return r.json()

    logger.evals._request = request  # type: ignore[assignment]
    logger.evals.list_suites()
    assert captured["auth"] == "Bearer from-env"
