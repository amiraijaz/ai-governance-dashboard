import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_registry.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    prompt_hash: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    user_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(50), default="success", nullable=False)
    flagged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    flag_severity: Mapped[Optional[str]] = mapped_column(String(20))
    extra_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(
        "metadata", JSONB, nullable=True
    )

    model: Mapped["ModelRegistry"] = relationship(back_populates="audit_logs")  # noqa: F821
    safety_flags: Mapped[list["SafetyFlag"]] = relationship(  # noqa: F821
        back_populates="log", cascade="all, delete-orphan"
    )
