"""Dashboard-backed evals — talks to /api/evals on the user's Vigil instance.

Unlike `AIGovLogger.call` (which swallows logging failures so the host app
is never affected), eval calls return real results. They are SYNCHRONOUS,
they DO raise on error, and they use the same Bearer token the user
authenticates to the dashboard with — not the X-API-Key header used by
the log-ingest path.

Authentication note: the dashboard's /api/evals endpoints require the
session JWT, not the ingest API key. Pass `token=...` (the access_token
returned from /api/auth/login) when constructing the client, OR set
``AIGOV_TOKEN`` in the environment.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx

from .errors import DashboardError


class DashboardEvals:
    """Thin sync client for /api/evals. Exposed via ``logger.evals``."""

    def __init__(
        self,
        dashboard_url: str,
        token: Optional[str] = None,
        timeout_s: float = 30.0,
    ) -> None:
        self.dashboard_url = dashboard_url.rstrip("/")
        self.token = token or os.getenv("AIGOV_TOKEN", "").strip()
        self.timeout_s = timeout_s

    # ------------------------------------------------------------------
    # HTTP plumbing
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise DashboardError(
                "Dashboard-backed evals need a session token. Pass "
                "`token=` when constructing the logger, or set AIGOV_TOKEN "
                "to your /api/auth/login access_token."
            )
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.dashboard_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                r = client.request(method, url, headers=self._headers(), **kwargs)
        except httpx.HTTPError as exc:
            raise DashboardError(f"{method} {path} failed: {exc}") from exc
        if r.status_code >= 400:
            detail: Any
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            raise DashboardError(
                f"{method} {path} returned {r.status_code}: {detail}"
            )
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError as exc:
            raise DashboardError(
                f"{method} {path} returned non-JSON body"
            ) from exc

    # ------------------------------------------------------------------
    # Public methods — small, opinionated, mirror the router
    # ------------------------------------------------------------------

    def create_suite(
        self,
        name: str,
        eval_type: str,
        config: dict,
        model_id: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict:
        payload: dict[str, Any] = {
            "name": name,
            "eval_type": eval_type,
            "config": config,
        }
        if model_id is not None:
            payload["model_id"] = model_id
        if description is not None:
            payload["description"] = description
        return self._request("POST", "/api/evals/suites", json=payload)

    def list_suites(
        self,
        eval_type: Optional[str] = None,
        model_id: Optional[str] = None,
    ) -> list[dict]:
        params = {}
        if eval_type:
            params["eval_type"] = eval_type
        if model_id:
            params["model_id"] = model_id
        return self._request("GET", "/api/evals/suites", params=params)

    def get_suite(self, suite_id: str) -> dict:
        return self._request("GET", f"/api/evals/suites/{suite_id}")

    def delete_suite(self, suite_id: str) -> None:
        self._request("DELETE", f"/api/evals/suites/{suite_id}")

    def run_suite(
        self,
        suite_id: str,
        cases: Optional[list[dict]] = None,
    ) -> dict:
        """Trigger a run. Returns ``{"run_id", "status", "message"}``.
        The run executes asynchronously on the dashboard; poll ``get_run``
        until ``status`` is ``"complete"`` or ``"failed"``.
        """
        body = {"cases": cases} if cases is not None else {}
        return self._request("POST", f"/api/evals/suites/{suite_id}/run", json=body)

    def get_run(self, run_id: str) -> dict:
        return self._request("GET", f"/api/evals/runs/{run_id}")

    def get_run_results(
        self, run_id: str, page: int = 1, limit: int = 50,
    ) -> dict:
        return self._request(
            "GET", f"/api/evals/runs/{run_id}/results",
            params={"page": page, "limit": limit},
        )
