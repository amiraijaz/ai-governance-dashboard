"""Pydantic schemas for the eval framework HTTP API.

Note the ``protected_namespaces=()`` on every model that has a ``model_id``
field — pydantic v2 reserves the ``model_`` prefix and emits a warning at
import time otherwise. This is the same trick used by ``schemas/pricing.py``
and ``schemas/model_registry.py`` elsewhere in the app.
"""

import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


EvalType = Literal["rag", "llm_judge", "drift"]


# ---------------------------------------------------------------------------
# Suite
# ---------------------------------------------------------------------------


class SuiteBase(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    eval_type: EvalType
    # Free-form per-type config; shape is validated by validate_suite_config
    # in the router so we can return a clear 422 instead of a Pydantic blob.
    config: dict[str, Any] = Field(default_factory=dict)
    model_id: Optional[uuid.UUID] = None


class SuiteCreate(SuiteBase):
    pass


class SuiteUpdate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    model_id: Optional[uuid.UUID] = None


class SuiteResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=(), from_attributes=True)

    id: uuid.UUID
    name: str
    description: Optional[str]
    eval_type: str
    config: Optional[dict[str, Any]]
    model_id: Optional[uuid.UUID]
    owner_email: Optional[str]
    created_at: datetime
    updated_at: datetime


class SuiteDetail(SuiteResponse):
    """Suite + its recent runs, returned by GET /evals/suites/{id}."""
    recent_runs: list["RunResponse"] = []


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


class RunTriggerRequest(BaseModel):
    """Optional payload for POST /evals/suites/{id}/run.

    If ``cases`` is omitted the run uses the suite's configured case source
    (``from_logs`` if set, otherwise an empty case set with a note in the
    summary). Drift runs ignore ``cases`` entirely.
    """
    cases: Optional[list[dict[str, Any]]] = None


class RunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    suite_id: uuid.UUID
    status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    summary: Optional[dict[str, Any]]
    error_message: Optional[str]
    triggered_by: Optional[str]
    created_at: datetime


class RunCreated(BaseModel):
    """Body of the 202 response when a run is triggered."""
    run_id: uuid.UUID
    status: str
    message: str


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


class ResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    log_id: Optional[uuid.UUID]
    case_input: Optional[str]
    case_output: Optional[str]
    scores: Optional[dict[str, Any]]
    passed: bool
    details: Optional[dict[str, Any]]
    created_at: datetime


class PaginatedResults(BaseModel):
    items: list[ResultResponse]
    page: int
    limit: int
    total: int


# Resolve forward ref now that RunResponse exists.
SuiteDetail.model_rebuild()
