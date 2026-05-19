import uuid
from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


ReviewStatus = Literal["safe", "issue_found", "escalated"]


class FlagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: uuid.UUID
    log_id: uuid.UUID
    model_id: uuid.UUID
    model_name: Optional[str] = None
    timestamp: datetime
    flag_type: str
    severity: str
    confidence: float
    details: Optional[dict[str, Any]] = None
    reviewed: bool
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_status: Optional[str] = None
    review_notes: Optional[str] = None


class FlagDetail(FlagResponse):
    prompt_hash: Optional[str] = None
    log_metadata: Optional[dict[str, Any]] = Field(default=None)


class FlagReviewRequest(BaseModel):
    review_status: ReviewStatus
    review_notes: Optional[str] = None


class PaginatedFlags(BaseModel):
    items: List[FlagResponse]
    page: int
    limit: int
    total: int


class FlagStats(BaseModel):
    total: int
    open: int
    green: int
    yellow: int
    red: int
    reviewed_today: int
