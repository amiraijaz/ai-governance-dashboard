import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_admin
from app.schemas.pricing import (
    PricingOut,
    PricingUpdate,
    ProviderSyncStatus,
    SyncStatus,
    SyncSummary,
)
from database import get_db
from models import ModelPricing, User
from services.pricing_sync import pricing_sync_service

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/", response_model=List[PricingOut])
async def list_pricing(
    provider: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ModelPricing).order_by(ModelPricing.provider, ModelPricing.model_key)
    if provider is not None:
        stmt = stmt.where(ModelPricing.provider == provider)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("/sync", response_model=SyncSummary)
async def trigger_sync(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    return await pricing_sync_service.sync_all(db)


@router.get("/sync/status", response_model=SyncStatus)
async def sync_status(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(
            ModelPricing.provider,
            func.count(ModelPricing.id),
            func.max(ModelPricing.last_synced_at),
        ).group_by(ModelPricing.provider)
    )
    rows = result.all()
    providers = [
        ProviderSyncStatus(provider=p, model_count=c, last_synced_at=ts)
        for p, c, ts in rows
    ]
    total = sum(p.model_count for p in providers)
    return SyncStatus(providers=providers, total_models=total)


@router.put("/{pricing_id}", response_model=PricingOut)
async def update_pricing(
    pricing_id: uuid.UUID,
    payload: PricingUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ModelPricing).where(ModelPricing.id == pricing_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Pricing row not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    await db.commit()
    await db.refresh(row)
    return row
