import csv
import hashlib
import io
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import sys

from fastapi import BackgroundTasks

from app.auth import get_current_user
from app.schemas.audit_log import AuditLogCreate, AuditLogResponse, PaginatedLogs
from database import AsyncSessionLocal, get_db
from models import APIKey, AuditLog, ModelRegistry, SafetyFlag
from services.cost_calculator import get_cost_result
from services.safety_checker import safety_checker

router = APIRouter(dependencies=[Depends(get_current_user)])
ingest_router = APIRouter()


def _apply_filters(
    stmt,
    model_id: Optional[uuid.UUID],
    status_: Optional[str],
    flagged: Optional[bool],
    date_from: Optional[datetime],
    date_to: Optional[datetime],
):
    if model_id is not None:
        stmt = stmt.where(AuditLog.model_id == model_id)
    if status_ is not None:
        stmt = stmt.where(AuditLog.status == status_)
    if flagged is not None:
        stmt = stmt.where(AuditLog.flagged == flagged)
    if date_from is not None:
        stmt = stmt.where(AuditLog.timestamp >= date_from)
    if date_to is not None:
        stmt = stmt.where(AuditLog.timestamp <= date_to)
    return stmt


@router.get("/", response_model=PaginatedLogs)
async def list_logs(
    db: AsyncSession = Depends(get_db),
    model_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    flagged: Optional[bool] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
):
    base = _apply_filters(select(AuditLog), model_id, status, flagged, date_from, date_to)

    total = await db.scalar(
        _apply_filters(
            select(func.count(AuditLog.id)),
            model_id,
            status,
            flagged,
            date_from,
            date_to,
        )
    )

    result = await db.execute(
        base.order_by(AuditLog.timestamp.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    items = result.scalars().all()
    return PaginatedLogs(items=items, page=page, limit=limit, total=total or 0)


@router.get("/export/csv")
async def export_csv(
    db: AsyncSession = Depends(get_db),
    model_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
    flagged: Optional[bool] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
):
    stmt = _apply_filters(
        select(AuditLog).order_by(AuditLog.timestamp.desc()),
        model_id,
        status,
        flagged,
        date_from,
        date_to,
    )

    columns = [
        "id",
        "model_id",
        "timestamp",
        "prompt_hash",
        "prompt_tokens",
        "completion_tokens",
        "total_cost_usd",
        "latency_ms",
        "user_id",
        "session_id",
        "status",
        "flagged",
        "flag_severity",
    ]

    async def row_stream():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(columns)
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)

        result = await db.stream(stmt)
        async for row in result.scalars():
            writer.writerow([getattr(row, c) for c in columns])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    return StreamingResponse(
        row_stream(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_logs.csv"},
    )


@router.get("/{log_id}", response_model=AuditLogResponse)
async def get_log(log_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AuditLog).where(AuditLog.id == log_id))
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="Log not found")
    return log


async def verify_api_key(
    db: AsyncSession,
    raw_key: Optional[str],
) -> APIKey:
    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-API-Key header"
        )
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    result = await db.execute(
        select(APIKey).where(APIKey.key_hash == key_hash, APIKey.is_active.is_(True))
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key"
        )
    return api_key


async def run_safety_check(
    log_id: uuid.UUID,
    model_id: uuid.UUID,
    response_text: str,
    db_session_factory,
) -> None:
    """Background task: run safety checks on the response and persist flags.

    Owns its own DB session because the request session closes as soon as
    the 201 response is flushed. Never raises — failure is logged.
    """
    try:
        async with db_session_factory() as db:
            result = await safety_checker.check(response_text)
            if not result.get("flagged"):
                return

            await db.execute(
                update(AuditLog)
                .where(AuditLog.id == log_id)
                .values(flagged=True, flag_severity=result["severity"])
            )
            for f in result["flags"]:
                details = (
                    f["details"]
                    if isinstance(f["details"], dict)
                    else {"value": f["details"]}
                )
                db.add(
                    SafetyFlag(
                        log_id=log_id,
                        model_id=model_id,
                        flag_type=f["type"],
                        severity=result["severity"],
                        confidence=float(f["confidence"]),
                        details=details,
                    )
                )
            await db.commit()
    except Exception as exc:
        print(f"[safety] background check failed for log {log_id}: {exc}", file=sys.stderr)


@ingest_router.post(
    "/",
    response_model=AuditLogResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_log(
    payload: AuditLogCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    api_key = await verify_api_key(db, x_api_key)

    model = (
        await db.execute(
            select(ModelRegistry).where(ModelRegistry.id == payload.model_id)
        )
    ).scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=404, detail="model_id not found")

    cost_result = await get_cost_result(
        db, model.model_version, payload.prompt_tokens, payload.completion_tokens
    )

    payload_data = payload.model_dump(by_alias=False, exclude_none=False)
    response_text = payload_data.pop("response_text", None)
    extra_metadata = payload_data.pop("extra_metadata", None) or {}
    if cost_result.matched_key is None:
        extra_metadata["warning"] = "UNKNOWN_MODEL"
        extra_metadata["model_version"] = model.model_version

    entry = AuditLog(
        **payload_data,
        total_cost_usd=cost_result.cost,
        extra_metadata=extra_metadata or None,
    )
    db.add(entry)

    await db.execute(
        update(APIKey)
        .where(APIKey.id == api_key.id)
        .values(last_used_at=func.now())
    )

    await db.commit()
    await db.refresh(entry)

    if response_text:
        background_tasks.add_task(
            run_safety_check,
            entry.id,
            entry.model_id,
            response_text,
            AsyncSessionLocal,
        )

    return entry
