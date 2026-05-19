import uuid
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class AuditLogCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    model_id: uuid.UUID
    prompt_hash: Optional[str] = Field(default=None, max_length=128)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    status: str = "success"
    flagged: bool = False
    flag_severity: Optional[str] = None
    response_text: Optional[str] = None
    extra_metadata: Optional[dict[str, Any]] = Field(
        default=None, validation_alias="metadata", serialization_alias="metadata"
    )


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    model_id: uuid.UUID
    timestamp: datetime
    prompt_hash: Optional[str]
    prompt_tokens: int
    completion_tokens: int
    total_cost_usd: float
    latency_ms: int
    user_id: Optional[str]
    session_id: Optional[str]
    status: str
    flagged: bool
    flag_severity: Optional[str]
    extra_metadata: Optional[dict[str, Any]] = Field(
        default=None, serialization_alias="metadata"
    )


class PaginatedLogs(BaseModel):
    items: List[AuditLogResponse]
    page: int
    limit: int
    total: int
