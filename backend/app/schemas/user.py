import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr


Role = Literal["viewer", "admin"]


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    role: str
    organisation: Optional[str]
    created_at: datetime


class UserRoleUpdate(BaseModel):
    role: Role
