"""Background task for generating compliance reports.

The HTTP endpoint inserts a Report row with status='pending' and schedules
this task. The task owns its own DB session because the request session
closes before it runs. Failures are persisted on the row, not raised.
"""

import sys
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

from sqlalchemy import update

from models import Report
from services.report_generator import ReportGenerator

REPORTS_DIR = Path(__file__).resolve().parents[1] / "generated_reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


async def generate_report_task(
    report_id: uuid.UUID,
    db_factory,
    date_from: date,
    date_to: date,
    model_ids: Optional[list[str]],
    organisation: Optional[str],
) -> None:
    async with db_factory() as db:
        try:
            generator = ReportGenerator()
            pdf_bytes = await generator.generate(
                db,
                date_from=date_from,
                date_to=date_to,
                model_ids=model_ids,
                organisation=organisation,
            )
            file_path = REPORTS_DIR / f"{report_id}.pdf"
            file_path.write_bytes(pdf_bytes)

            await db.execute(
                update(Report)
                .where(Report.id == report_id)
                .values(
                    status="complete",
                    file_path=str(file_path),
                    file_size_bytes=len(pdf_bytes),
                )
            )
            await db.commit()
        except Exception as exc:
            print(
                f"[reports] generation failed for {report_id}: {exc}",
                file=sys.stderr,
            )
            try:
                await db.execute(
                    update(Report)
                    .where(Report.id == report_id)
                    .values(status="failed", error_message=str(exc)[:1000])
                )
                await db.commit()
            except Exception as exc2:
                print(
                    f"[reports] could not record failure for {report_id}: {exc2}",
                    file=sys.stderr,
                )
