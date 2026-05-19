import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.schemas.report import ReportCreate, ReportCreated, ReportSummary
from database import AsyncSessionLocal, get_db
from models import Report, User
from services.report_queue import REPORTS_DIR, generate_report_task

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post(
    "/generate",
    response_model=ReportCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_report(
    payload: ReportCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if payload.format == "csv":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV format is not implemented yet — use 'pdf'.",
        )
    if payload.date_to < payload.date_from:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date_to must be on or after date_from",
        )

    model_ids = (
        [str(mid) for mid in payload.model_ids] if payload.model_ids else None
    )

    report = Report(
        user_id=user.id,
        date_from=payload.date_from,
        date_to=payload.date_to,
        model_ids=model_ids,
        status="pending",
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    background_tasks.add_task(
        generate_report_task,
        report.id,
        AsyncSessionLocal,
        payload.date_from,
        payload.date_to,
        model_ids,
        user.organisation,
    )

    return ReportCreated(
        id=report.id,
        status=report.status,
        message="Report is being generated",
    )


@router.get("/", response_model=List[ReportSummary])
async def list_reports(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Report)
        .where(Report.user_id == user.id)
        .order_by(Report.generated_at.desc())
    )
    return result.scalars().all()


@router.get("/{report_id}", response_model=ReportSummary)
async def get_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if not report or report.user_id != user.id:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.get("/{report_id}/download")
async def download_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()
    if not report or report.user_id != user.id:
        raise HTTPException(status_code=404, detail="Report not found")

    if report.status != "complete":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Report is {report.status}, not ready for download",
        )
    if not report.file_path:
        raise HTTPException(status_code=410, detail="Report file is missing")
    path = Path(report.file_path)
    if not path.exists():
        raise HTTPException(status_code=410, detail="Report file is missing")

    filename = f"aigov-report-{report.date_to.isoformat()}.pdf"
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=filename,
    )
