"""aigovkit.evals — evaluation framework, two modes.

MODE A — local execution (the SDK computes evals itself):
    from aigovkit.evals import judge, rag, drift

    # judge: just an API key, no extras needed
    result = judge(cases, rubric=YAML_STRING)

    # rag: requires the [evals] extras for ragas + langchain
    #     pip install aigovkit[evals]
    result = rag(cases, threshold=0.7)

    # drift: stdlib-only sample comparison
    result = drift(current=[...], baseline=[...])

MODE B — dashboard-backed (recommended for teams):
    from aigovkit import AIGovLogger
    logger = AIGovLogger(api_key="sk_...", model_id="<uuid>",
                        dashboard_url="https://your-vigil",
                        token="<session JWT>")
    suite = logger.evals.create_suite(
        name="Support quality", eval_type="llm_judge",
        config={"rubric": YAML_STRING},
    )
    run = logger.evals.run_suite(suite["id"], cases=[...])
    final = logger.evals.get_run(run["run_id"])

Errors raised by this package all inherit from ``EvalError`` — catch that
to handle any eval failure generically.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional, Union

from ._dashboard import DashboardEvals
from ._drift import detect as _drift_detect
from ._judge import (
    DEFAULT_CONCURRENCY as _JUDGE_CONCURRENCY,
    DEFAULT_JUDGE_TIMEOUT_S as _JUDGE_TIMEOUT,
    DEFAULT_PASS_THRESHOLD as _JUDGE_THRESHOLD,
    Rubric,
    RubricCriterion,
    _judge_async,
    parse_rubric,
)
from ._rag import _rag_async
from .errors import (
    DashboardError,
    EvalDependenciesNotInstalled,
    EvalError,
    NoLLMConfigured,
    RubricError,
)

__all__ = [
    # local-mode evals
    "judge",
    "rag",
    "drift",
    # rubric helpers
    "Rubric",
    "RubricCriterion",
    "parse_rubric",
    # dashboard-mode client (instantiated by AIGovLogger.evals)
    "DashboardEvals",
    # errors
    "EvalError",
    "EvalDependenciesNotInstalled",
    "RubricError",
    "NoLLMConfigured",
    "DashboardError",
]


# ---------------------------------------------------------------------------
# Local-mode entry points — sync wrappers around async impls so the SDK
# user does not need an event loop. If the caller IS already in an event
# loop (e.g. inside Jupyter or FastAPI), import the async variants
# (_judge_async / _rag_async) directly.
# ---------------------------------------------------------------------------


def judge(
    cases: list[dict],
    rubric: Union[str, dict, Rubric],
    threshold: Optional[float] = None,
    concurrency: int = _JUDGE_CONCURRENCY,
    timeout_s: float = _JUDGE_TIMEOUT,
) -> dict:
    """LLM-as-judge evaluation against a rubric.

    Args:
        cases:       list of ``{"input": "...", "output": "..."}`` dicts
        rubric:      YAML string, plain dict, or pre-parsed Rubric
        threshold:   override the rubric's pass_threshold
        concurrency: max in-flight judge calls (default 5)
        timeout_s:   per-call HTTP timeout

    Returns ``{"per_case": [...], "summary": {...}}``.

    Needs ``ANTHROPIC_API_KEY`` or ``OPENAI_API_KEY`` in the env.
    Anthropic is preferred; OpenAI is the fallback.
    """
    parsed = parse_rubric(rubric)
    if threshold is not None:
        parsed = Rubric(
            name=parsed.name,
            criteria=parsed.criteria,
            pass_threshold=float(threshold),
        )
    return asyncio.run(_judge_async(cases, parsed, concurrency, timeout_s))


def rag(cases: list[dict], threshold: float = 0.7) -> dict:
    """Reference-free RAG evaluation (faithfulness / answer_relevancy /
    context_precision).

    Requires the optional ``aigovkit[evals]`` extras. Without them, raises
    ``EvalDependenciesNotInstalled`` with a one-line install hint.

    Each case must have ``query``, ``response``, and ``contexts``
    (list[str]); ``ground_truth`` is optional.
    """
    return asyncio.run(_rag_async(cases, threshold))


def drift(
    current,
    baseline,
    pct_threshold: float = 25.0,
    min_samples: int = 10,
) -> dict:
    """Two-sample drift on a single metric.

    Stdlib-only — see ``aigovkit.evals._drift`` for the rationale and the
    pointer to ``logger.evals.run_suite`` for full multi-signal drift
    against your audit logs.
    """
    return _drift_detect(current, baseline, pct_threshold, min_samples)
