from datetime import datetime, timedelta, timezone
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Float, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.schemas.analytics import (
    AnalyticsSummary,
    CostBucket,
    CostDriver,
    CostSparkPoint,
    LatencyBucket,
    MetricDelta,
    ModelBreakdown,
    RequestBucket,
    RiskBreakdown,
    SeverityBreakdown,
    TopModel,
)
from database import get_db
from models import AuditLog, ModelRegistry, SafetyFlag

router = APIRouter(dependencies=[Depends(get_current_user)])

Period = Literal["7d", "30d", "90d"]
PERIOD_DAYS: dict[str, int] = {"7d": 7, "30d": 30, "90d": 90}


def _period_start(period: str) -> datetime:
    days = PERIOD_DAYS.get(period)
    if days is None:
        raise HTTPException(status_code=400, detail="period must be 7d, 30d, or 90d")
    return datetime.now(timezone.utc) - timedelta(days=days)


@router.get("/cost", response_model=List[CostBucket])
async def cost_analytics(
    period: Period = "30d",
    group_by: Literal["day", "model", "team"] = "day",
    db: AsyncSession = Depends(get_db),
):
    start = _period_start(period)
    total = func.coalesce(func.sum(AuditLog.total_cost_usd), 0.0).label("total_cost_usd")
    count = func.count(AuditLog.id).label("request_count")

    if group_by == "day":
        day = func.date_trunc("day", AuditLog.timestamp).label("day")
        stmt = (
            select(day, total, count)
            .where(AuditLog.timestamp >= start)
            .group_by(day)
            .order_by(day)
        )
        rows = (await db.execute(stmt)).all()
        return [
            CostBucket(label=r.day.date().isoformat(), total_cost_usd=float(r.total_cost_usd), request_count=r.request_count)
            for r in rows
        ]

    if group_by == "model":
        stmt = (
            select(ModelRegistry.name.label("label"), total, count)
            .join(ModelRegistry, ModelRegistry.id == AuditLog.model_id)
            .where(AuditLog.timestamp >= start)
            .group_by(ModelRegistry.name)
            .order_by(total.desc())
        )
    else:  # team
        team_label = func.coalesce(ModelRegistry.owner_team, "(unassigned)").label("label")
        stmt = (
            select(team_label, total, count)
            .join(ModelRegistry, ModelRegistry.id == AuditLog.model_id)
            .where(AuditLog.timestamp >= start)
            .group_by(team_label)
            .order_by(total.desc())
        )
    rows = (await db.execute(stmt)).all()
    return [
        CostBucket(label=r.label, total_cost_usd=float(r.total_cost_usd), request_count=r.request_count)
        for r in rows
    ]


@router.get("/requests", response_model=List[RequestBucket])
async def requests_analytics(
    period: Period = "30d",
    db: AsyncSession = Depends(get_db),
):
    start = _period_start(period)
    day = func.date_trunc("day", AuditLog.timestamp).label("day")
    stmt = (
        select(
            day,
            func.count(AuditLog.id).label("count"),
            func.sum(case((AuditLog.status == "success", 1), else_=0)).label("success_count"),
            func.sum(case((AuditLog.status == "error", 1), else_=0)).label("error_count"),
            func.sum(case((AuditLog.flagged.is_(True), 1), else_=0)).label("flagged_count"),
        )
        .where(AuditLog.timestamp >= start)
        .group_by(day)
        .order_by(day)
    )
    rows = (await db.execute(stmt)).all()
    return [
        RequestBucket(
            date=r.day.date(),
            count=r.count,
            success_count=int(r.success_count or 0),
            error_count=int(r.error_count or 0),
            flagged_count=int(r.flagged_count or 0),
        )
        for r in rows
    ]


@router.get("/latency", response_model=List[LatencyBucket])
async def latency_analytics(
    period: Period = "30d",
    db: AsyncSession = Depends(get_db),
):
    start = _period_start(period)
    day = func.date_trunc("day", AuditLog.timestamp).label("day")
    latency = cast(AuditLog.latency_ms, Float)
    stmt = (
        select(
            day,
            func.coalesce(func.avg(latency), 0.0).label("avg_latency_ms"),
            func.coalesce(
                func.percentile_cont(0.95).within_group(latency.asc()), 0.0
            ).label("p95_latency_ms"),
            func.coalesce(
                func.percentile_cont(0.99).within_group(latency.asc()), 0.0
            ).label("p99_latency_ms"),
        )
        .where(AuditLog.timestamp >= start)
        .group_by(day)
        .order_by(day)
    )
    rows = (await db.execute(stmt)).all()
    return [
        LatencyBucket(
            date=r.day.date(),
            avg_latency_ms=float(r.avg_latency_ms),
            p95_latency_ms=float(r.p95_latency_ms),
            p99_latency_ms=float(r.p99_latency_ms),
        )
        for r in rows
    ]


@router.get("/models", response_model=List[ModelBreakdown])
async def models_analytics(db: AsyncSession = Depends(get_db)):
    stmt = (
        select(
            ModelRegistry.name.label("model_name"),
            ModelRegistry.provider.label("provider"),
            func.count(AuditLog.id).label("total_calls"),
            func.coalesce(func.sum(AuditLog.total_cost_usd), 0.0).label("total_cost_usd"),
            func.coalesce(func.avg(cast(AuditLog.latency_ms, Float)), 0.0).label("avg_latency_ms"),
            func.coalesce(
                func.sum(AuditLog.prompt_tokens + AuditLog.completion_tokens), 0
            ).label("total_tokens"),
        )
        .join(AuditLog, AuditLog.model_id == ModelRegistry.id)
        .group_by(ModelRegistry.id, ModelRegistry.name, ModelRegistry.provider)
        .order_by(func.count(AuditLog.id).desc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        ModelBreakdown(
            model_name=r.model_name,
            provider=r.provider,
            total_calls=r.total_calls,
            total_cost_usd=float(r.total_cost_usd),
            avg_latency_ms=float(r.avg_latency_ms),
            total_tokens=int(r.total_tokens),
        )
        for r in rows
    ]


def _pct_change(current: float, previous: float) -> float | None:
    """Symmetric delta helper. None when the previous window was empty
    so the UI can fall back to showing the absolute current instead of
    rendering a meaningless ∞%."""
    if previous == 0:
        return None
    return ((current - previous) / previous) * 100.0


@router.get("/summary", response_model=AnalyticsSummary)
async def summary(db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    thirty_days_ago = now - timedelta(days=30)
    sixty_days_ago = now - timedelta(days=60)

    models_registered = await db.scalar(select(func.count(ModelRegistry.id))) or 0

    calls_this_month = await db.scalar(
        select(func.count(AuditLog.id)).where(AuditLog.timestamp >= month_start)
    ) or 0

    cost_this_month = await db.scalar(
        select(func.coalesce(func.sum(AuditLog.total_cost_usd), 0.0)).where(
            AuditLog.timestamp >= month_start
        )
    ) or 0.0

    open_flags = await db.scalar(
        select(func.count(SafetyFlag.id)).where(SafetyFlag.reviewed.is_(False))
    ) or 0

    day = func.date_trunc("day", AuditLog.timestamp).label("day")
    spark_rows = (
        await db.execute(
            select(day, func.coalesce(func.sum(AuditLog.total_cost_usd), 0.0).label("cost"))
            .where(AuditLog.timestamp >= thirty_days_ago)
            .group_by(day)
            .order_by(day)
        )
    ).all()
    cost_last_30_days = [
        CostSparkPoint(date=r.day.date(), cost=float(r.cost)) for r in spark_rows
    ]

    top_rows = (
        await db.execute(
            select(ModelRegistry.name, func.count(AuditLog.id).label("calls"))
            .join(AuditLog, AuditLog.model_id == ModelRegistry.id)
            .group_by(ModelRegistry.name)
            .order_by(func.count(AuditLog.id).desc())
            .limit(5)
        )
    ).all()
    top_models = [TopModel(name=r.name, calls=r.calls) for r in top_rows]

    # --- Risk-level breakdown ---------------------------------------------
    risk_rows = (
        await db.execute(
            select(ModelRegistry.risk_level, func.count(ModelRegistry.id))
            .group_by(ModelRegistry.risk_level)
        )
    ).all()
    risk_counts = {level: count for level, count in risk_rows}
    added_this_month = await db.scalar(
        select(func.count(ModelRegistry.id)).where(ModelRegistry.created_at >= month_start)
    ) or 0
    models_by_risk = RiskBreakdown(
        low=int(risk_counts.get("Low", 0)),
        medium=int(risk_counts.get("Medium", 0)),
        high=int(risk_counts.get("High", 0)),
        critical=int(risk_counts.get("Critical", 0)),
        added_this_month=int(added_this_month),
    )

    # --- Top cost drivers (last 30 days) ----------------------------------
    cost_total_30d = float(
        await db.scalar(
            select(func.coalesce(func.sum(AuditLog.total_cost_usd), 0.0)).where(
                AuditLog.timestamp >= thirty_days_ago
            )
        ) or 0.0
    )
    driver_rows = (
        await db.execute(
            select(
                ModelRegistry.name,
                func.coalesce(func.sum(AuditLog.total_cost_usd), 0.0).label("cost"),
            )
            .join(AuditLog, AuditLog.model_id == ModelRegistry.id)
            .where(AuditLog.timestamp >= thirty_days_ago)
            .group_by(ModelRegistry.name)
            .order_by(func.sum(AuditLog.total_cost_usd).desc())
            .limit(3)
        )
    ).all()
    top_cost_models = [
        CostDriver(
            name=r.name,
            cost=float(r.cost),
            share_pct=(float(r.cost) / cost_total_30d * 100.0) if cost_total_30d > 0 else 0.0,
        )
        for r in driver_rows
    ]

    # --- Open-flags by severity -------------------------------------------
    sev_rows = (
        await db.execute(
            select(SafetyFlag.severity, func.count(SafetyFlag.id))
            .where(SafetyFlag.reviewed.is_(False))
            .group_by(SafetyFlag.severity)
        )
    ).all()
    sev_counts = {sev: count for sev, count in sev_rows}
    open_flags_by_severity = SeverityBreakdown(
        red=int(sev_counts.get("RED", 0)),
        yellow=int(sev_counts.get("YELLOW", 0)),
        green=int(sev_counts.get("GREEN", 0)),
    )

    # --- Period-over-period deltas (last 30d vs prior 30d) ----------------
    prev_window = (AuditLog.timestamp >= sixty_days_ago, AuditLog.timestamp < thirty_days_ago)
    curr_window = (AuditLog.timestamp >= thirty_days_ago,)

    calls_curr = int(await db.scalar(
        select(func.count(AuditLog.id)).where(*curr_window)
    ) or 0)
    calls_prev = int(await db.scalar(
        select(func.count(AuditLog.id)).where(*prev_window)
    ) or 0)
    cost_curr = float(await db.scalar(
        select(func.coalesce(func.sum(AuditLog.total_cost_usd), 0.0)).where(*curr_window)
    ) or 0.0)
    cost_prev = float(await db.scalar(
        select(func.coalesce(func.sum(AuditLog.total_cost_usd), 0.0)).where(*prev_window)
    ) or 0.0)

    # Flag-creation counts (not "open" — open is point-in-time). Trending
    # how many flags the system raised over time is the meaningful signal.
    flags_curr = int(await db.scalar(
        select(func.count(SafetyFlag.id)).where(
            SafetyFlag.timestamp >= thirty_days_ago
        )
    ) or 0)
    flags_prev = int(await db.scalar(
        select(func.count(SafetyFlag.id)).where(
            SafetyFlag.timestamp >= sixty_days_ago,
            SafetyFlag.timestamp < thirty_days_ago,
        )
    ) or 0)

    return AnalyticsSummary(
        models_registered=int(models_registered),
        calls_this_month=int(calls_this_month),
        cost_this_month=float(cost_this_month),
        open_flags=int(open_flags),
        cost_last_30_days=cost_last_30_days,
        top_models=top_models,
        models_by_risk=models_by_risk,
        top_cost_models=top_cost_models,
        open_flags_by_severity=open_flags_by_severity,
        calls_delta=MetricDelta(
            current=calls_curr, previous=calls_prev,
            pct_change=_pct_change(calls_curr, calls_prev),
        ),
        cost_delta=MetricDelta(
            current=cost_curr, previous=cost_prev,
            pct_change=_pct_change(cost_curr, cost_prev),
        ),
        flags_delta=MetricDelta(
            current=flags_curr, previous=flags_prev,
            pct_change=_pct_change(flags_curr, flags_prev),
        ),
    )
