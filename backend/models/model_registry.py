import uuid
from datetime import datetime, date
from typing import Optional

from sqlalchemy import String, Date, DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    use_case: Mapped[Optional[str]] = mapped_column(String(255))
    owner_team: Mapped[Optional[str]] = mapped_column(String(255))
    owner_email: Mapped[Optional[str]] = mapped_column(String(255))
    deployment_date: Mapped[Optional[date]] = mapped_column(Date)
    risk_level: Mapped[str] = mapped_column(String(20), default="Low", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="Active", nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    audit_logs: Mapped[list["AuditLog"]] = relationship(  # noqa: F821
        back_populates="model", cascade="all, delete-orphan"
    )
    safety_flags: Mapped[list["SafetyFlag"]] = relationship(  # noqa: F821
        back_populates="model", cascade="all, delete-orphan"
    )
