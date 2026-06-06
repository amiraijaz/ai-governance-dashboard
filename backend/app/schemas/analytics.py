from datetime import date as date_type
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class CostBucket(BaseModel):
    label: str
    total_cost_usd: float
    request_count: int


class RequestBucket(BaseModel):
    date: date_type
    count: int
    success_count: int
    error_count: int
    flagged_count: int


class LatencyBucket(BaseModel):
    date: date_type
    avg_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float


class ModelBreakdown(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_name: str
    provider: str
    total_calls: int
    total_cost_usd: float
    avg_latency_ms: float
    total_tokens: int


class CostSparkPoint(BaseModel):
    date: date_type
    cost: float


class TopModel(BaseModel):
    name: str
    calls: int


class MetricDelta(BaseModel):
    """Current 30-day window vs the prior 30-day window.

    `pct_change` is None when the previous window was zero (a percent change
    against zero is meaningless); the UI should fall back to showing the
    absolute current value in that case.
    """
    current: float
    previous: float
    pct_change: Optional[float] = None


class RiskBreakdown(BaseModel):
    low: int
    medium: int
    high: int
    critical: int
    added_this_month: int


class CostDriver(BaseModel):
    name: str
    cost: float
    share_pct: float


class SeverityBreakdown(BaseModel):
    red: int
    yellow: int
    green: int


class AnalyticsSummary(BaseModel):
    models_registered: int
    calls_this_month: int
    cost_this_month: float
    open_flags: int
    cost_last_30_days: List[CostSparkPoint]
    top_models: List[TopModel]

    # New: card-specific visuals + honest period-over-period deltas.
    models_by_risk: RiskBreakdown
    top_cost_models: List[CostDriver]
    open_flags_by_severity: SeverityBreakdown
    calls_delta: MetricDelta
    cost_delta: MetricDelta
    flags_delta: MetricDelta
