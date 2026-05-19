import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr


class ModelBase(BaseModel):
    name: str
    provider: str
    model_version: str
    use_case: Optional[str] = None
    owner_team: Optional[str] = None
    owner_email: Optional[EmailStr] = None
    deployment_date: Optional[date] = None
    risk_level: str = "Low"
    status: str = "Active"
    description: Optional[str] = None


class ModelCreate(ModelBase):
    pass


class ModelUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    model_version: Optional[str] = None
    use_case: Optional[str] = None
    owner_team: Optional[str] = None
    owner_email: Optional[EmailStr] = None
    deployment_date: Optional[date] = None
    risk_level: Optional[str] = None
    status: Optional[str] = None
    description: Optional[str] = None


class ModelOut(ModelBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class PaginatedModels(BaseModel):
    items: list[ModelOut]
    total: int
    page: int
    pages: int
