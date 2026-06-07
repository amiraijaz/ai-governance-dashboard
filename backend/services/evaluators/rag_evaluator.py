"""Reference-free RAG evaluation via Ragas.

Three metrics, all reference-free (no `ground_truth` required):

* ``faithfulness``       — is the response grounded in the retrieved contexts?
* ``answer_relevancy``   — does the response actually address the query?
* ``context_precision``  — were the retrieved contexts relevant to the query?

Design notes
------------
* Ragas + LangChain are **lazily imported** inside ``_run_ragas``. The API
  process can boot without them resident; the cost only materialises when an
  EvalRun actually fires.
* ``_run_ragas`` is sync (Ragas is sync internally) and is dispatched through
  ``asyncio.to_thread`` from ``evaluate``, so it never blocks the event loop.
* ``_run_ragas`` returns ``list[dict[str, float]]`` — plain Python — rather
  than a Ragas-specific object. That keeps the public ``evaluate`` pure and
  the test suite trivially mockable (no pandas / no datasets needed at test
  time).
* No silent zeros on missing API keys. If neither ``ANTHROPIC_API_KEY`` nor
  ``OPENAI_API_KEY`` is set we raise ``NoLLMConfigured`` so the operator gets
  a clear error instead of a fake-perfect score sheet.
"""

from __future__ import annotations

import asyncio
import os
from statistics import mean
from typing import Any

METRIC_NAMES: tuple[str, ...] = (
    "faithfulness",
    "answer_relevancy",
    "context_precision",
)

REQUIRED_CASE_KEYS = ("query", "response", "contexts")


class RAGEvaluatorError(RuntimeError):
    """Base class for evaluator failures."""


class NoLLMConfigured(RAGEvaluatorError):
    """Raised when no LLM provider key is available to drive the judges."""


class EvalDependenciesNotInstalled(RAGEvaluatorError):
    """Raised when the eval-execution deps (ragas / datasets / langchain-*)
    are missing at runtime. The main API image deliberately ships without
    them — install requirements-evals.txt in the eval worker or local dev."""


def _validate_cases(cases: list[dict]) -> None:
    for i, c in enumerate(cases):
        missing = [k for k in REQUIRED_CASE_KEYS if k not in c]
        if missing:
            raise RAGEvaluatorError(
                f"case {i} is missing required key(s): {missing}"
            )
        if not isinstance(c["contexts"], list):
            raise RAGEvaluatorError(
                f"case {i} 'contexts' must be a list[str], got {type(c['contexts']).__name__}"
            )


class RAGEvaluator:
    def __init__(self, threshold: float = 0.7) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"threshold must be in [0,1], got {threshold}")
        self.threshold = threshold

    # ------------------------------------------------------------------
    # Provider wiring
    # ------------------------------------------------------------------

    def _check_provider_keys(self) -> tuple[str, str]:
        """Pure env-var validation, runs BEFORE any lazy imports.

        Returns ``(anthropic_key, openai_key)`` with empty strings for unset.
        Raises ``NoLLMConfigured`` with a clear message if the configuration
        can't drive the eval. Keeping this separate from the import-heavy
        ``_build_llm_and_embeddings`` lets the no-key error path fire without
        ever touching langchain / ragas / datasets — critical so the operator
        sees the real problem instead of ``ModuleNotFoundError: datasets``.
        """
        anthropic_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
        openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        if not anthropic_key and not openai_key:
            raise NoLLMConfigured(
                "No LLM provider configured for RAG evaluation. "
                "Set ANTHROPIC_API_KEY or OPENAI_API_KEY before running an eval."
            )
        # Embeddings always come from OpenAI — Anthropic has no public
        # embeddings endpoint, and Ragas needs an embedder for context_precision.
        if not openai_key:
            raise NoLLMConfigured(
                "OPENAI_API_KEY is required for Ragas embeddings (the answer "
                "judge can still use Anthropic). Set OPENAI_API_KEY alongside "
                "ANTHROPIC_API_KEY."
            )
        return anthropic_key, openai_key

    def _build_llm_and_embeddings(self) -> tuple[Any, Any]:
        """Construct the judge LLM + embeddings. Heavy imports live here so
        the no-key path never has to touch them. Called from inside
        ``_run_ragas`` after ``_check_provider_keys`` has already passed."""
        anthropic_key, openai_key = self._check_provider_keys()

        try:
            from langchain_openai import OpenAIEmbeddings  # noqa: WPS433
            if anthropic_key:
                from langchain_anthropic import ChatAnthropic  # noqa: WPS433
            else:
                from langchain_openai import ChatOpenAI  # noqa: WPS433
        except ModuleNotFoundError as exc:
            raise EvalDependenciesNotInstalled(
                "Eval execution requires: pip install -r requirements-evals.txt "
                f"(missing module: {exc.name})"
            ) from exc

        embeddings = OpenAIEmbeddings(api_key=openai_key, model="text-embedding-3-small")
        if anthropic_key:
            llm = ChatAnthropic(model="claude-haiku-4-5", api_key=anthropic_key, temperature=0)
        else:
            llm = ChatOpenAI(model="gpt-4o-mini", api_key=openai_key, temperature=0)
        return llm, embeddings

    # ------------------------------------------------------------------
    # Ragas wrapper — sync, lazily imports the heavy deps.
    # Returns plain list[dict[str, float]] so the public evaluate() never
    # touches Ragas types.
    # ------------------------------------------------------------------

    def _run_ragas(self, cases: list[dict]) -> list[dict[str, float]]:
        try:
            from datasets import Dataset  # noqa: WPS433
            from ragas import evaluate as ragas_evaluate  # noqa: WPS433
            from ragas.metrics import (  # noqa: WPS433
                answer_relevancy,
                context_precision,
                faithfulness,
            )
        except ModuleNotFoundError as exc:
            raise EvalDependenciesNotInstalled(
                "Eval execution requires: pip install -r requirements-evals.txt "
                f"(missing module: {exc.name})"
            ) from exc

        llm, embeddings = self._build_llm_and_embeddings()

        dataset_dict: dict[str, Any] = {
            "question": [c["query"] for c in cases],
            "answer": [c["response"] for c in cases],
            "contexts": [list(c["contexts"]) for c in cases],
        }
        if any("ground_truth" in c for c in cases):
            dataset_dict["ground_truth"] = [c.get("ground_truth", "") for c in cases]

        ds = Dataset.from_dict(dataset_dict)
        result = ragas_evaluate(
            ds,
            metrics=[faithfulness, answer_relevancy, context_precision],
            llm=llm,
            embeddings=embeddings,
        )
        df = result.to_pandas()

        rows: list[dict[str, float]] = []
        for _, row in df.iterrows():
            scores = {}
            for name in METRIC_NAMES:
                if name in row and row[name] is not None:
                    try:
                        scores[name] = float(row[name])
                    except (TypeError, ValueError):
                        continue
            rows.append(scores)
        return rows

    # ------------------------------------------------------------------
    # Public async entry point
    # ------------------------------------------------------------------

    async def evaluate(self, cases: list[dict]) -> dict:
        if not cases:
            return self._empty_result()

        _validate_cases(cases)
        # Fail fast on missing keys BEFORE spinning up the thread that does
        # the heavy ragas / datasets imports — otherwise the operator sees a
        # ModuleNotFoundError instead of the real "set ANTHROPIC_API_KEY".
        self._check_provider_keys()

        per_case_scores = await asyncio.to_thread(self._run_ragas, cases)

        per_case: list[dict] = []
        for i, scores in enumerate(per_case_scores):
            case_passed = (
                bool(scores) and all(v >= self.threshold for v in scores.values())
            )
            per_case.append(
                {
                    "index": i,
                    "query": cases[i]["query"],
                    "scores": scores,
                    "passed": case_passed,
                }
            )

        # Aggregate per metric (mean over cases where the metric was computed).
        agg_metrics: dict[str, float] = {}
        for name in METRIC_NAMES:
            xs = [c["scores"][name] for c in per_case if name in c["scores"]]
            if xs:
                agg_metrics[name] = mean(xs)

        passed = sum(1 for c in per_case if c["passed"])
        total = len(per_case)
        return {
            "per_case": per_case,
            "summary": {
                "total_cases": total,
                "passed": passed,
                "failed": total - passed,
                "pass_rate": passed / total if total else 0.0,
                "threshold": self.threshold,
                "metrics": agg_metrics,
            },
        }

    @staticmethod
    def _empty_result() -> dict:
        return {
            "per_case": [],
            "summary": {
                "total_cases": 0,
                "passed": 0,
                "failed": 0,
                "pass_rate": 0.0,
                "threshold": 0.0,
                "metrics": {},
            },
        }
