"""Background execution of EvalRuns.

This task owns its own DB session because by the time it runs, the request
session that scheduled it has closed (same pattern as the safety check
post-ingest and the WeasyPrint report generator).

Contract:
- never raises out of the task (any uncaught exception sets the run's
  ``status='failed'`` with the exception message)
- never leaves a run stuck in ``running``
- catches ``EvalDependenciesNotInstalled`` specifically so the operator
  sees the "pip install -r requirements-evals.txt" hint, not a generic
  500-style traceback
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, update

from models import AuditLog, EvalResult, EvalRun, EvalSuite, ModelRegistry
from services.evaluators import (
    DriftDetector,
    EvalDependenciesNotInstalled,
    JudgeEvaluator,
    NoLLMConfigured,
    RAGEvaluator,
)


async def run_eval_task(
    run_id: uuid.UUID,
    session_factory,
    inline_cases: Optional[list[dict[str, Any]]] = None,
) -> None:
    """Execute an EvalRun. Owns its own session; never raises out."""
    async with session_factory() as db:
        try:
            await _mark_running(db, run_id)
            run = (await db.execute(select(EvalRun).where(EvalRun.id == run_id))).scalar_one()
            suite = (await db.execute(select(EvalSuite).where(EvalSuite.id == run.suite_id))).scalar_one()

            eval_type = suite.eval_type
            config = suite.config or {}

            if eval_type == "drift":
                summary, per_case = await _run_drift(db, suite, config)
            elif eval_type == "rag":
                summary, per_case = await _run_rag(db, suite, config, inline_cases)
            elif eval_type == "llm_judge":
                summary, per_case = await _run_judge(db, suite, config, inline_cases)
            else:
                raise ValueError(f"unknown eval_type: {eval_type!r}")

            for r in per_case:
                db.add(EvalResult(run_id=run_id, **r))

            await db.execute(
                update(EvalRun)
                .where(EvalRun.id == run_id)
                .values(
                    status="complete",
                    completed_at=datetime.now(timezone.utc),
                    summary=summary,
                    error_message=None,
                )
            )
            await db.commit()

        except EvalDependenciesNotInstalled as exc:
            # Friendly install hint — surfaced verbatim in the dashboard.
            await _mark_failed(db, run_id, str(exc))
        except NoLLMConfigured as exc:
            await _mark_failed(db, run_id, str(exc))
        except Exception as exc:  # noqa: BLE001 — bucket for "any other failure"
            print(f"[eval] run {run_id} failed: {exc!r}", file=sys.stderr)
            await _mark_failed(db, run_id, f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


async def _mark_running(db, run_id: uuid.UUID) -> None:
    await db.execute(
        update(EvalRun)
        .where(EvalRun.id == run_id)
        .values(status="running", started_at=datetime.now(timezone.utc))
    )
    await db.commit()


async def _mark_failed(db, run_id: uuid.UUID, message: str) -> None:
    try:
        await db.rollback()  # discard any partial state from the failed path
    except Exception:  # noqa: BLE001
        pass
    await db.execute(
        update(EvalRun)
        .where(EvalRun.id == run_id)
        .values(
            status="failed",
            completed_at=datetime.now(timezone.utc),
            error_message=message,
        )
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Per-type dispatchers — each returns (summary_dict, per_case_rows)
# ---------------------------------------------------------------------------


async def _run_drift(db, suite: EvalSuite, config: dict) -> tuple[dict, list[dict]]:
    target_model_id = suite.model_id or config.get("model_id")
    if target_model_id is None:
        raise ValueError(
            "drift suite needs a target model: set suite.model_id "
            "or include 'model_id' in the config"
        )
    detector = DriftDetector(
        latency_pct_threshold=float(config.get("latency_pct_threshold", 25.0)),
        length_pct_threshold=float(config.get("length_pct_threshold", 25.0)),
        error_rate_delta_threshold=float(config.get("error_rate_delta_threshold", 0.10)),
        p_value_threshold=float(config.get("p_value_threshold", 0.05)),
    )
    result = await detector.detect(
        db,
        model_id=target_model_id,
        current_days=int(config.get("current_days", 7)),
        baseline_days=int(config.get("baseline_days", 7)),
    )
    # Drift produces a structured signals dict, not per-case rows. The full
    # report lives in summary so the dashboard can render it directly.
    return result, []


async def _run_rag(
    db, suite: EvalSuite, config: dict, inline_cases: Optional[list[dict]]
) -> tuple[dict, list[dict]]:
    cases, note = await _resolve_cases(db, suite, config, inline_cases)
    if not cases:
        return ({"note": note, "total_cases": 0}, [])

    threshold = float(config.get("threshold", 0.7))
    result = await RAGEvaluator(threshold=threshold).evaluate(cases)
    return result["summary"], _per_case_rag_rows(cases, result["per_case"])


async def _run_judge(
    db, suite: EvalSuite, config: dict, inline_cases: Optional[list[dict]]
) -> tuple[dict, list[dict]]:
    cases, note = await _resolve_cases(db, suite, config, inline_cases)
    if not cases:
        return ({"note": note, "total_cases": 0}, [])

    rubric_yaml = config.get("rubric")
    if not isinstance(rubric_yaml, str):
        raise ValueError("llm_judge suite config is missing required 'rubric' string")

    judge = JudgeEvaluator(concurrency=int(config.get("concurrency", 5)))
    rubric = judge.parse_rubric(rubric_yaml)
    result = await judge.evaluate(cases, rubric)
    return result["summary"], _per_case_judge_rows(cases, result["per_case"])


# ---------------------------------------------------------------------------
# Case sourcing
# ---------------------------------------------------------------------------


async def _resolve_cases(
    db,
    suite: EvalSuite,
    config: dict,
    inline_cases: Optional[list[dict]],
) -> tuple[list[dict], Optional[str]]:
    """Inline wins if provided. Otherwise pull from audit_logs per the
    suite's ``from_logs`` filter. Returns ``(cases, note)``; the note
    surfaces in the run summary when no cases were found."""
    if inline_cases:
        return inline_cases, None

    source = (config.get("source") or "inline").lower()
    if source != "from_logs":
        return [], "no inline cases provided and suite source != 'from_logs'"

    flt = config.get("filter") or {}
    stmt = select(AuditLog)
    target_model_id = suite.model_id or flt.get("model_id")
    if target_model_id is not None:
        stmt = stmt.where(AuditLog.model_id == target_model_id)
    limit = int(flt.get("limit", 50))
    stmt = stmt.order_by(AuditLog.timestamp.desc()).limit(limit)
    logs = (await db.execute(stmt)).scalars().all()

    cases: list[dict] = []
    for log in logs:
        meta = log.extra_metadata or {}
        # The default audit log only stores prompt_hash, not raw text. Some
        # callers stash text in extra_metadata (e.g. eval seeders). When
        # nothing is available we deliberately skip the row rather than
        # invent inputs.
        case_input = meta.get("prompt") or meta.get("input")
        case_output = meta.get("response") or meta.get("output")
        if not case_input or not case_output:
            continue
        cases.append({
            "input": case_input,
            "output": case_output,
            "query": case_input,
            "response": case_output,
            "contexts": meta.get("contexts", []),
            "log_id": str(log.id),
        })

    if not cases:
        return [], (
            "from_logs returned 0 usable cases — audit_logs don't store raw "
            "prompt/response text by default. Run with inline cases or wire "
            "your ingest to stash text under extra_metadata.prompt/response."
        )
    return cases, None


# ---------------------------------------------------------------------------
# Per-case row construction
# ---------------------------------------------------------------------------


def _per_case_rag_rows(cases: list[dict], per_case: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for i, case in enumerate(per_case):
        src = cases[i] if i < len(cases) else {}
        log_id = _coerce_uuid(src.get("log_id"))
        rows.append({
            "log_id": log_id,
            "case_input": src.get("query") or src.get("input"),
            "case_output": src.get("response") or src.get("output"),
            "scores": case.get("scores") or {},
            "passed": bool(case.get("passed")),
            "details": {"contexts": src.get("contexts", [])},
        })
    return rows


def _per_case_judge_rows(cases: list[dict], per_case: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for i, case in enumerate(per_case):
        src = cases[i] if i < len(cases) else {}
        log_id = _coerce_uuid(src.get("log_id"))
        details: dict[str, Any] = {}
        if case.get("error"):
            details["error"] = case["error"]
        if case.get("raw"):
            details["raw"] = case["raw"]
        if case.get("mean_score") is not None:
            details["mean_score"] = case["mean_score"]
        rows.append({
            "log_id": log_id,
            "case_input": case.get("input") or src.get("input"),
            "case_output": case.get("output") or src.get("output"),
            "scores": case.get("scores") or {},
            "passed": bool(case.get("passed")),
            "details": details or None,
        })
    return rows


def _coerce_uuid(maybe_id) -> Optional[uuid.UUID]:
    if maybe_id is None:
        return None
    if isinstance(maybe_id, uuid.UUID):
        return maybe_id
    try:
        return uuid.UUID(str(maybe_id))
    except (TypeError, ValueError):
        return None
