"""Eval framework HTTP API.

All routes are protected by ``get_current_user``. Suites are owner-scoped
(same pattern as API keys and reports) — the user who created a suite is
the only one who can read, update, delete, or trigger runs against it.
Cross-user access returns 404 (not 403) so we don't leak existence.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.schemas.evaluation import (
    PaginatedResults,
    ResultResponse,
    RunCreated,
    RunResponse,
    RunTriggerRequest,
    SuiteCreate,
    SuiteDetail,
    SuiteResponse,
    SuiteUpdate,
)
from database import AsyncSessionLocal, get_db
from models import EvalResult, EvalRun, EvalSuite, User
from services.eval_runner import run_eval_task
from services.evaluators import JudgeEvaluator, RubricError

router = APIRouter(dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------------
# Per-type config validation
# ---------------------------------------------------------------------------


def _validate_suite_config(eval_type: str, config: dict) -> None:
    """422 with a specific message instead of a generic Pydantic blob.

    rag        : optional ``threshold`` must be numeric in [0,1]
    llm_judge  : required ``rubric`` YAML must parse cleanly
    drift      : optional ``current_days`` / ``baseline_days`` must be >= 1 ints
    """
    if eval_type == "rag":
        if "threshold" in config:
            t = config["threshold"]
            if not isinstance(t, (int, float)) or not 0 <= float(t) <= 1:
                raise HTTPException(422, detail="rag.threshold must be a number in [0,1]")

    elif eval_type == "llm_judge":
        rubric_yaml = config.get("rubric")
        if not isinstance(rubric_yaml, str) or not rubric_yaml.strip():
            raise HTTPException(
                422, detail="llm_judge config requires a non-empty 'rubric' YAML string"
            )
        try:
            JudgeEvaluator().parse_rubric(rubric_yaml)
        except RubricError as exc:
            raise HTTPException(422, detail=f"invalid rubric: {exc}") from exc

    elif eval_type == "drift":
        for k in ("current_days", "baseline_days"):
            if k in config:
                v = config[k]
                if not isinstance(v, int) or isinstance(v, bool) or v < 1:
                    raise HTTPException(
                        422, detail=f"drift.{k} must be a positive integer"
                    )


# ---------------------------------------------------------------------------
# Ownership helper — fetch a suite the current user owns, or raise 404
# ---------------------------------------------------------------------------


async def _get_owned_suite(
    suite_id: uuid.UUID, db: AsyncSession, user: User
) -> EvalSuite:
    suite = (
        await db.execute(select(EvalSuite).where(EvalSuite.id == suite_id))
    ).scalar_one_or_none()
    if suite is None or suite.owner_email != user.email:
        raise HTTPException(status_code=404, detail="Suite not found")
    return suite


async def _get_owned_run(
    run_id: uuid.UUID, db: AsyncSession, user: User
) -> EvalRun:
    row = (
        await db.execute(
            select(EvalRun, EvalSuite)
            .join(EvalSuite, EvalSuite.id == EvalRun.suite_id)
            .where(EvalRun.id == run_id)
        )
    ).first()
    if row is None or row.EvalSuite.owner_email != user.email:
        raise HTTPException(status_code=404, detail="Run not found")
    return row.EvalRun


# ===========================================================================
# Suites
# ===========================================================================


@router.post(
    "/suites",
    response_model=SuiteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_suite(
    payload: SuiteCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _validate_suite_config(payload.eval_type, payload.config)
    suite = EvalSuite(
        name=payload.name,
        description=payload.description,
        eval_type=payload.eval_type,
        config=payload.config,
        model_id=payload.model_id,
        owner_email=user.email,
    )
    db.add(suite)
    await db.commit()
    await db.refresh(suite)
    return suite


@router.get("/suites", response_model=list[SuiteResponse])
async def list_suites(
    eval_type: Optional[str] = None,
    model_id: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(EvalSuite).where(EvalSuite.owner_email == user.email)
    if eval_type is not None:
        stmt = stmt.where(EvalSuite.eval_type == eval_type)
    if model_id is not None:
        stmt = stmt.where(EvalSuite.model_id == model_id)
    stmt = stmt.order_by(EvalSuite.created_at.desc())
    return (await db.execute(stmt)).scalars().all()


@router.get("/suites/{suite_id}", response_model=SuiteDetail)
async def get_suite(
    suite_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    suite = await _get_owned_suite(suite_id, db, user)
    recent = (
        await db.execute(
            select(EvalRun)
            .where(EvalRun.suite_id == suite.id)
            .order_by(EvalRun.created_at.desc())
            .limit(10)
        )
    ).scalars().all()
    detail = SuiteDetail.model_validate(suite)
    detail.recent_runs = [RunResponse.model_validate(r) for r in recent]
    return detail


@router.put("/suites/{suite_id}", response_model=SuiteResponse)
async def update_suite(
    suite_id: uuid.UUID,
    payload: SuiteUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    suite = await _get_owned_suite(suite_id, db, user)
    if payload.config is not None:
        _validate_suite_config(suite.eval_type, payload.config)
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(suite, k, v)
    await db.commit()
    await db.refresh(suite)
    return suite


@router.delete("/suites/{suite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_suite(
    suite_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    suite = await _get_owned_suite(suite_id, db, user)
    await db.delete(suite)  # cascades to runs + results
    await db.commit()


# ===========================================================================
# Runs
# ===========================================================================


@router.post(
    "/suites/{suite_id}/run",
    response_model=RunCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_run(
    suite_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    payload: Optional[RunTriggerRequest] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    suite = await _get_owned_suite(suite_id, db, user)

    run = EvalRun(
        suite_id=suite.id,
        status="pending",
        triggered_by=user.email,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    inline_cases = payload.cases if payload else None
    background_tasks.add_task(
        run_eval_task,
        run.id,
        AsyncSessionLocal,
        inline_cases,
    )

    return RunCreated(
        run_id=run.id,
        status=run.status,
        message=f"{suite.eval_type} run queued",
    )


@router.get("/runs", response_model=list[RunResponse])
async def list_runs(
    limit: int = Query(50, ge=1, le=500),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Scoped to runs whose parent suite is owned by the user.
    stmt = (
        select(EvalRun)
        .join(EvalSuite, EvalSuite.id == EvalRun.suite_id)
        .where(EvalSuite.owner_email == user.email)
        .order_by(EvalRun.created_at.desc())
        .limit(limit)
    )
    if status_filter is not None:
        stmt = stmt.where(EvalRun.status == status_filter)
    return (await db.execute(stmt)).scalars().all()


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _get_owned_run(run_id, db, user)


@router.get("/runs/{run_id}/results", response_model=PaginatedResults)
async def list_run_results(
    run_id: uuid.UUID,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_owned_run(run_id, db, user)
    total = await db.scalar(
        select(func.count(EvalResult.id)).where(EvalResult.run_id == run_id)
    ) or 0
    items = (
        await db.execute(
            select(EvalResult)
            .where(EvalResult.run_id == run_id)
            .order_by(EvalResult.created_at.asc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
    ).scalars().all()
    return PaginatedResults(items=items, page=page, limit=limit, total=total)
