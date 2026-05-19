import hashlib
import secrets
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.schemas.api_key import APIKeyCreate, APIKeyCreated, APIKeyInfo
from database import get_db
from models import APIKey, User

router = APIRouter()


@router.post("/", response_model=APIKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_key(
    payload: APIKeyCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    raw_key = secrets.token_bytes(32).hex()
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    api_key = APIKey(user_id=user.id, key_hash=key_hash, name=payload.name)
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return APIKeyCreated(
        id=api_key.id,
        name=api_key.name,
        created_at=api_key.created_at,
        last_used_at=api_key.last_used_at,
        is_active=api_key.is_active,
        key=raw_key,
    )


@router.get("/", response_model=List[APIKeyInfo])
async def list_keys(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(APIKey).where(APIKey.user_id == user.id).order_by(APIKey.created_at.desc())
    )
    return result.scalars().all()


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_key(
    key_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(APIKey).where(APIKey.id == key_id))
    api_key = result.scalar_one_or_none()
    if not api_key or api_key.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key not found")
    api_key.is_active = False
    await db.commit()
