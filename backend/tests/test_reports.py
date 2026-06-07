"""Report generation tests.

The background generator (services.report_queue.generate_report_task) drives
WeasyPrint + a Jinja template. Both are heavy and depend on system libs, so
we replace ``generate_report_task`` with a stub that writes a tiny placeholder
PDF to the temp reports dir and flips the row's status. The route-level
contract (202 → pending → polling → file download) is what's under test, not
the PDF rendering itself (that's covered by the WeasyPrint suite).
"""

import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
import pytest_asyncio


# A minimal but valid 1-page PDF. Used by the stubbed background task so the
# download endpoint has a real file to serve.
TINY_PDF_BYTES = (
    b"%PDF-1.1\n"
    b"1 0 obj <</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj <</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
    b"3 0 obj <</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n0000000010 00000 n \n"
    b"0000000051 00000 n \n0000000095 00000 n \n"
    b"trailer <</Size 4/Root 1 0 R>>\n"
    b"startxref\n145\n%%EOF\n"
)


@pytest_asyncio.fixture(autouse=True)
async def _stub_report_generator(monkeypatch, tmp_path):
    """Replace generate_report_task with a stub that:

    1. Writes a tiny valid PDF to a tmp dir.
    2. Updates the Report row (via its own session, just like the real task).
    """
    from services import report_queue as rq_mod
    from sqlalchemy import update
    from models import Report

    out_path = tmp_path / "report.pdf"

    async def fake_task(
        report_id, session_factory, date_from, date_to, model_ids, organisation
    ):
        out_path.write_bytes(TINY_PDF_BYTES)
        async with session_factory() as db:
            await db.execute(
                update(Report)
                .where(Report.id == report_id)
                .values(
                    status="complete",
                    file_path=str(out_path),
                    file_size_bytes=len(TINY_PDF_BYTES),
                )
            )
            await db.commit()

    monkeypatch.setattr(rq_mod, "generate_report_task", fake_task)
    # The router imported the symbol by name; patch the router's binding too.
    from app.routers import reports as reports_router
    monkeypatch.setattr(reports_router, "generate_report_task", fake_task)
    yield out_path


# ---------------------------------------------------------------------------
# Generate + status flip
# ---------------------------------------------------------------------------


async def test_generate_returns_202_pending(auth_client):
    today = date.today()
    r = await auth_client.post(
        "/api/reports/generate",
        json={
            "date_from": (today - timedelta(days=7)).isoformat(),
            "date_to": today.isoformat(),
            "format": "pdf",
        },
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] in ("pending", "complete")  # task may finish before the JSON serialises
    assert "id" in body
    assert "message" in body


async def test_background_task_flips_status_to_complete(auth_client, db_session):
    today = date.today()
    r = await auth_client.post(
        "/api/reports/generate",
        json={
            "date_from": (today - timedelta(days=7)).isoformat(),
            "date_to": today.isoformat(),
            "format": "pdf",
        },
    )
    report_id = r.json()["id"]

    # The stub completes synchronously inside the background task that
    # httpx+ASGITransport awaits before returning the response. By the time
    # we get here, the row is already complete.
    from sqlalchemy import select
    from models import Report

    # Use a fresh query so we see the latest committed state.
    await db_session.commit()
    report = (
        await db_session.execute(select(Report).where(Report.id == uuid.UUID(report_id)))
    ).scalar_one()
    await db_session.refresh(report)
    assert report.status == "complete"
    assert report.file_path is not None
    assert Path(report.file_path).exists()


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


async def test_owner_can_download_completed_report(auth_client):
    today = date.today()
    gen = await auth_client.post(
        "/api/reports/generate",
        json={
            "date_from": (today - timedelta(days=7)).isoformat(),
            "date_to": today.isoformat(),
            "format": "pdf",
        },
    )
    report_id = gen.json()["id"]

    r = await auth_client.get(f"/api/reports/{report_id}/download")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    # The stub writes a 4-line ASCII PDF — first bytes are the magic.
    assert r.content.startswith(b"%PDF-")


async def test_cross_user_download_is_404(auth_client, client):
    today = date.today()
    gen = await auth_client.post(
        "/api/reports/generate",
        json={
            "date_from": (today - timedelta(days=7)).isoformat(),
            "date_to": today.isoformat(),
            "format": "pdf",
        },
    )
    report_id = gen.json()["id"]

    # Build a second, unrelated user on the bare `client`.
    await client.post(
        "/api/auth/register",
        json={"email": "snoop@example.com", "password": "TestPass123!"},
    )
    login = await client.post(
        "/api/auth/login",
        json={"email": "snoop@example.com", "password": "TestPass123!"},
    )
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

    r = await client.get(f"/api/reports/{report_id}/download")
    # We deliberately return 404 (not 403) so we don't confirm the report
    # exists to non-owners. That's the load-bearing security contract here.
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


async def test_csv_format_is_rejected(auth_client):
    today = date.today()
    r = await auth_client.post(
        "/api/reports/generate",
        json={
            "date_from": (today - timedelta(days=7)).isoformat(),
            "date_to": today.isoformat(),
            "format": "csv",
        },
    )
    assert r.status_code == 400
    assert "csv" in r.json()["detail"].lower()


async def test_date_to_before_date_from_is_400(auth_client):
    today = date.today()
    r = await auth_client.post(
        "/api/reports/generate",
        json={
            "date_from": today.isoformat(),
            "date_to": (today - timedelta(days=1)).isoformat(),
            "format": "pdf",
        },
    )
    assert r.status_code == 400
