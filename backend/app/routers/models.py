import math
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.schemas.model_registry import (
    ModelCreate,
    ModelOut,
    ModelUpdate,
    PaginatedModels,
)
from database import get_db
from models import ModelRegistry, User

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/", response_model=PaginatedModels)
async def list_models(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
):
    total = await db.scalar(select(func.count(ModelRegistry.id))) or 0
    result = await db.execute(
        select(ModelRegistry)
        .order_by(ModelRegistry.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    items = result.scalars().all()
    pages = max(1, math.ceil(total / limit)) if total else 1
    return PaginatedModels(items=items, total=total, page=page, pages=pages)


@router.post("/", response_model=ModelOut, status_code=status.HTTP_201_CREATED)
async def create_model(
    payload: ModelCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    entry = ModelRegistry(**payload.model_dump())
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.get("/{model_id}", response_model=ModelOut)
async def get_model(model_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ModelRegistry).where(ModelRegistry.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


@router.patch("/{model_id}", response_model=ModelOut)
async def update_model(
    model_id: uuid.UUID,
    payload: ModelUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ModelRegistry).where(ModelRegistry.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(model, k, v)
    await db.commit()
    await db.refresh(model)
    return model


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(model_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ModelRegistry).where(ModelRegistry.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    await db.delete(model)
    await db.commit()
