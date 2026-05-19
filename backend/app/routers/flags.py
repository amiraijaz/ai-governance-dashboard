import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.schemas.safety_flag import (
    FlagDetail,
    FlagResponse,
    FlagReviewRequest,
    FlagStats,
    PaginatedFlags,
)
from database import get_db
from models import AuditLog, ModelRegistry, SafetyFlag, User

router = APIRouter(dependencies=[Depends(get_current_user)])


def _apply_filters(
    stmt,
    severity: Optional[str],
    reviewed: Optional[bool],
    model_id: Optional[uuid.UUID],
    date_from: Optional[datetime],
    date_to: Optional[datetime],
):
    if severity is not None:
        stmt = stmt.where(SafetyFlag.severity == severity)
    if reviewed is not None:
        stmt = stmt.where(SafetyFlag.reviewed.is_(reviewed))
    if model_id is not None:
        stmt = stmt.where(SafetyFlag.model_id == model_id)
    if date_from is not None:
        stmt = stmt.where(SafetyFlag.timestamp >= date_from)
    if date_to is not None:
        stmt = stmt.where(SafetyFlag.timestamp <= date_to)
    return stmt


@router.get("/stats", response_model=FlagStats)
async def stats(db: AsyncSession = Depends(get_db)):
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    row = (
        await db.execute(
            select(
                func.count(SafetyFlag.id).label("total"),
                func.sum(case((SafetyFlag.reviewed.is_(False), 1), else_=0)).label("open"),
                func.sum(case((SafetyFlag.severity == "GREEN", 1), else_=0)).label("green"),
                func.sum(case((SafetyFlag.severity == "YELLOW", 1), else_=0)).label("yellow"),
                func.sum(case((SafetyFlag.severity == "RED", 1), else_=0)).label("red"),
                func.sum(
                    case((SafetyFlag.reviewed_at >= today_start, 1), else_=0)
                ).label("reviewed_today"),
            )
        )
    ).one()
    return FlagStats(
        total=int(row.total or 0),
        open=int(row.open or 0),
        green=int(row.green or 0),
        yellow=int(row.yellow or 0),
        red=int(row.red or 0),
        reviewed_today=int(row.reviewed_today or 0),
    )


@router.get("/", response_model=PaginatedFlags)
async def list_flags(
    severity: Optional[str] = None,
    reviewed: Optional[bool] = None,
    model_id: Optional[uuid.UUID] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    base = (
        select(SafetyFlag, ModelRegistry.name.label("model_name"))
        .join(ModelRegistry, ModelRegistry.id == SafetyFlag.model_id)
    )
    base = _apply_filters(base, severity, reviewed, model_id, date_from, date_to)

    count_stmt = _apply_filters(
        select(func.count(SafetyFlag.id)),
        severity,
        reviewed,
        model_id,
        date_from,
        date_to,
    )
    total = await db.scalar(count_stmt) or 0

    rows = (
        await db.execute(
            base.order_by(SafetyFlag.timestamp.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
    ).all()

    items = []
    for flag, model_name in rows:
        item = FlagResponse.model_validate(flag)
        item.model_name = model_name
        items.append(item)
    return PaginatedFlags(items=items, page=page, limit=limit, total=total)


@router.get("/{flag_id}", response_model=FlagDetail)
async def get_flag(flag_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    row = (
        await db.execute(
            select(
                SafetyFlag,
                ModelRegistry.name.label("model_name"),
                AuditLog.prompt_hash.label("prompt_hash"),
                AuditLog.extra_metadata.label("log_metadata"),
            )
            .join(ModelRegistry, ModelRegistry.id == SafetyFlag.model_id)
            .join(AuditLog, AuditLog.id == SafetyFlag.log_id)
            .where(SafetyFlag.id == flag_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Flag not found")

    flag, model_name, prompt_hash, log_metadata = row
    detail = FlagDetail.model_validate(flag)
    detail.model_name = model_name
    detail.prompt_hash = prompt_hash
    detail.log_metadata = log_metadata
    return detail


@router.put("/{flag_id}/review", response_model=FlagResponse)
async def review_flag(
    flag_id: uuid.UUID,
    payload: FlagReviewRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(SafetyFlag).where(SafetyFlag.id == flag_id))
    flag = result.scalar_one_or_none()
    if flag is None:
        raise HTTPException(status_code=404, detail="Flag not found")

    flag.reviewed = True
    flag.reviewed_by = user.email
    flag.reviewed_at = datetime.now(timezone.utc)
    flag.review_status = payload.review_status
    flag.review_notes = payload.review_notes
    await db.commit()
    await db.refresh(flag)

    model_name = await db.scalar(
        select(ModelRegistry.name).where(ModelRegistry.id == flag.model_id)
    )
    out = FlagResponse.model_validate(flag)
    out.model_name = model_name
    return out
