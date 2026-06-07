"""Evaluation framework tables.

Three-tier hierarchy:

    EvalSuite  ──┐        one named bundle of eval cases (a "suite")
                 │
    EvalRun  ◄───┘        one execution of that suite (pending → complete)
                 │
    EvalResult ◄─┘        per-case score + judge reasoning

Naming notes:
* ``EvalSuite.eval_type`` (not ``type``) avoids the Python/SA reserved
  attribute. Stored as a free-form String for forward compatibility —
  current values are ``rag``, ``llm_judge``, ``drift``.
* ``EvalResult.details`` carries judge reasoning, retrieved contexts,
  trace IDs. Kept as JSONB so the schema does not need to know the
  shape per eval_type.
* The metadata column on AuditLog had to be aliased to ``extra_metadata``
  because ``metadata`` collides with SQLAlchemy's Declarative attribute.
  We avoid that name here entirely.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class EvalSuite(Base):
    __tablename__ = "eval_suites"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    # rag | llm_judge | drift  (kept as String for forward compatibility)
    eval_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    config: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    # Optional: a suite can target a specific registered model or run ad-hoc.
    model_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_registry.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    owner_email: Mapped[Optional[str]] = mapped_column(String(255), index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    runs: Mapped[list["EvalRun"]] = relationship(
        back_populates="suite", cascade="all, delete-orphan"
    )


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    suite_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("eval_suites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # pending | running | complete | failed
    status: Mapped[str] = mapped_column(
        String(50), default="pending", nullable=False, index=True
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Aggregate scores, e.g.:
    #   {"faithfulness": 0.82, "answer_relevancy": 0.91,
    #    "total_cases": 50, "passed": 44}
    summary: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    # User email, or the literal string "scheduled" when fired by APScheduler.
    triggered_by: Mapped[Optional[str]] = mapped_column(String(255), index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    suite: Mapped["EvalSuite"] = relationship(back_populates="runs")
    results: Mapped[list["EvalResult"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class EvalResult(Base):
    __tablename__ = "eval_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("eval_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Optional back-link to the original audit log that produced this case —
    # SET NULL keeps eval history readable even after the log is purged.
    log_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("audit_logs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    case_input: Mapped[Optional[str]] = mapped_column(Text)
    case_output: Mapped[Optional[str]] = mapped_column(Text)
    # Per-metric scores for this case, e.g. {"faithfulness": 0.9, "groundedness": 0.85}
    scores: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    # Judge reasoning, retrieved contexts, intermediate traces, etc.
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped["EvalRun"] = relationship(back_populates="results")
