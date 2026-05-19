import uuid
from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict


class ReportCreate(BaseModel):
    date_from: date
    date_to: date
    model_ids: Optional[List[uuid.UUID]] = None
    format: Literal["pdf", "csv"] = "pdf"


class ReportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    generated_at: datetime
    date_from: date
    date_to: date
    file_size_bytes: Optional[int] = None
    status: str = "complete"
    error_message: Optional[str] = None


class ReportCreated(BaseModel):
    id: uuid.UUID
    status: str
    message: str
