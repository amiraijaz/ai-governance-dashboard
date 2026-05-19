import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class APIKeyCreate(BaseModel):
    name: Optional[str] = None


class APIKeyInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: Optional[str]
    created_at: datetime
    last_used_at: Optional[datetime]
    is_active: bool


class APIKeyCreated(APIKeyInfo):
    key: str
