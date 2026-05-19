import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class PricingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: uuid.UUID
    model_key: str
    provider: str
    prompt_cost_per_1k: Decimal
    completion_cost_per_1k: Decimal
    is_active: bool
    last_synced_at: Optional[datetime] = None
    updated_at: datetime


class PricingUpdate(BaseModel):
    provider: Optional[str] = None
    prompt_cost_per_1k: Optional[Decimal] = None
    completion_cost_per_1k: Optional[Decimal] = None
    is_active: Optional[bool] = None


class SyncSummary(BaseModel):
    synced: int
    updated: int
    errors: list[str]


class ProviderSyncStatus(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    provider: str
    model_count: int
    last_synced_at: Optional[datetime]


class SyncStatus(BaseModel):
    providers: list[ProviderSyncStatus]
    total_models: int
