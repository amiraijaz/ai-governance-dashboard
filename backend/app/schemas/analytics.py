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


class AnalyticsSummary(BaseModel):
    models_registered: int
    calls_this_month: int
    cost_this_month: float
    open_flags: int
    cost_last_30_days: List[CostSparkPoint]
    top_models: List[TopModel]
