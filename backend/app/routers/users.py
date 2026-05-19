import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.schemas.user import UserOut, UserRoleUpdate
from database import get_db
from models import User

router = APIRouter()


@router.put(
    "/{user_id}/role",
    response_model=UserOut,
    dependencies=[Depends(require_admin)],
)
async def update_user_role(
    user_id: uuid.UUID,
    payload: UserRoleUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if user_id == admin.id and payload.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot demote yourself",
        )
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.role = payload.role
    await db.commit()
    await db.refresh(user)
    return user
