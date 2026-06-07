"""Evaluator package — clean public entry points for the eval framework.

Callers (the SDK, the API router, scheduled jobs) talk to functions in this
module. They never import Ragas, LangChain, anthropic, openai, or any other
eval library directly. That layer is held inside the concrete evaluators so
the implementation can be swapped without breaking the contract.

Two evaluators live here today:

* ``RAGEvaluator`` (reference-free RAG metrics via Ragas) — heavy deps, lives
  in ``requirements-evals.txt``, raises ``EvalDependenciesNotInstalled`` if
  invoked without those deps present.
* ``JudgeEvaluator`` (LLM-as-judge against YAML rubrics) — light, uses only
  ``httpx`` + ``pyyaml`` from the main image, no extra install needed.
"""

from .drift_detector import DriftDetector
from .judge_evaluator import (
    JudgeEvaluator,
    Rubric,
    RubricCriterion,
    RubricError,
    evaluate_with_rubric,
)
from .rag_evaluator import (
    EvalDependenciesNotInstalled,
    NoLLMConfigured,
    RAGEvaluator,
    RAGEvaluatorError,
)

__all__ = [
    # RAG
    "RAGEvaluator",
    "RAGEvaluatorError",
    "NoLLMConfigured",
    "EvalDependenciesNotInstalled",
    "evaluate_rag",
    # Judge
    "JudgeEvaluator",
    "Rubric",
    "RubricCriterion",
    "RubricError",
    "evaluate_with_rubric",
    # Drift
    "DriftDetector",
]


async def evaluate_rag(
    cases: list[dict],
    threshold: float = 0.7,
) -> dict:
    """Reference-free RAG evaluation.

    Each case is a dict with keys:
      * ``query``        — the user's question
      * ``response``     — the system's answer
      * ``contexts``     — list[str] of retrieved chunks
      * ``ground_truth`` — optional reference answer

    Returns ``{"per_case": [...], "summary": {...}}``. A case passes when
    every computed metric is at or above ``threshold``.
    """
    return await RAGEvaluator(threshold=threshold).evaluate(cases)
