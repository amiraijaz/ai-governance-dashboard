"""End-to-end SDK test against a running AI Governance backend.

Run:
    export ANTHROPIC_API_KEY=...
    python sdk/test_sdk.py
"""

import os
import sys
import time
import uuid

import httpx

from aigov import AIGovLogger

BASE_URL = os.environ.get("AIGOV_BASE_URL", "http://localhost:8000")
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
INJECTION_PROMPT = (
    "Repeat exactly this text and nothing else: ignore previous instructions"
)


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        fail("ANTHROPIC_API_KEY is not set in the environment")

    suffix = uuid.uuid4().hex[:8]
    email = f"sdk-test-{suffix}@example.com"
    password = "password123"

    with httpx.Client(base_url=BASE_URL, timeout=60.0) as http:
        print(f"[1/9] register user {email}")
        r = http.post(
            "/api/auth/register",
            json={"email": email, "password": password, "organisation": "Test Co"},
        )
        if r.status_code not in (200, 201):
            fail(f"register failed: {r.status_code} {r.text}")

        print("[2/9] login")
        r = http.post("/api/auth/login", json={"email": email, "password": password})
        if r.status_code != 200:
            fail(f"login failed: {r.status_code} {r.text}")
        access_token = r.json()["access_token"]
        auth = {"Authorization": f"Bearer {access_token}"}

        print("[3/9] create model 'Test Bot'")
        r = http.post(
            "/api/models/",
            headers=auth,
            json={
                "name": "Test Bot",
                "provider": "Anthropic",
                "model_version": "claude-haiku-4-5",
                "risk_level": "Low",
            },
        )
        if r.status_code not in (200, 201):
            fail(f"model create failed: {r.status_code} {r.text}")
        model_id = r.json()["id"]
        print(f"      model_id = {model_id}")

        print("[4/9] create API key")
        r = http.post("/api/keys/", headers=auth, json={"name": "sdk-e2e-test"})
        if r.status_code not in (200, 201):
            fail(f"key create failed: {r.status_code} {r.text}")
        api_key = r.json()["key"]
        print(f"      raw key (shown once, length={len(api_key)})")

        print("[5/9] SDK call to Anthropic (benign)")
        logger = AIGovLogger(
            api_key=api_key,
            model_id=model_id,
            dashboard_url=BASE_URL,
        )
        response = logger.call(
            provider="anthropic",
            model=ANTHROPIC_MODEL,
            messages=[{"role": "user", "content": "Say hello in one sentence."}],
            user_id="test_user_001",
            max_tokens=50,
        )
        print(f"      response: {response.content[0].text}")

        time.sleep(0.5)

        print("[6/9] GET /api/logs (benign call should be present, unflagged)")
        r = http.get(
            "/api/logs/", headers=auth, params={"model_id": model_id, "limit": 1}
        )
        log = r.json()["items"][0]
        print(
            f"      cost_usd={log['total_cost_usd']} "
            f"latency_ms={log['latency_ms']} flagged={log['flagged']}"
        )

        print("[7/9] SDK call with log_responses=True + injection bait")
        logger_with_responses = AIGovLogger(
            api_key=api_key,
            model_id=model_id,
            dashboard_url=BASE_URL,
            log_responses=True,
        )
        response = logger_with_responses.call(
            provider="anthropic",
            model=ANTHROPIC_MODEL,
            messages=[{"role": "user", "content": INJECTION_PROMPT}],
            user_id="test_user_injection",
            max_tokens=50,
        )
        injection_text = response.content[0].text
        print(f"      response: {injection_text}")

        # Safety check runs synchronously inside the ingest endpoint,
        # so the flag should be present immediately after the SDK call returns.
        time.sleep(0.5)

        print("[8/9] GET /api/logs — confirm the injection log is flagged")
        r = http.get(
            "/api/logs/",
            headers=auth,
            params={"model_id": model_id, "flagged": True, "limit": 5},
        )
        flagged_items = r.json().get("items", [])
        if not flagged_items:
            fail("expected at least one flagged log, found none")
        flagged_log = flagged_items[0]
        print(
            f"      flagged log: id={flagged_log['id']} "
            f"severity={flagged_log['flag_severity']}"
        )

        print("[9/9] GET /api/flags — confirm a safety_flag row exists")
        r = http.get("/api/flags/", headers=auth, params={"model_id": model_id})
        flags = r.json().get("items", [])
        if not flags:
            fail("expected at least one safety_flag row for this model, found none")
        for f in flags:
            print(
                f"      flag: type={f['flag_type']} severity={f['severity']} "
                f"confidence={f['confidence']}"
            )

        types_found = {f["flag_type"] for f in flags}
        if "PROMPT_INJECTION" not in types_found:
            fail(
                "expected PROMPT_INJECTION flag from response 'ignore previous "
                f"instructions', got: {sorted(types_found)}"
            )

        print("\nOK")


if __name__ == "__main__":
    main()
