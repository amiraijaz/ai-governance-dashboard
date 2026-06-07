"""Reference-free RAG evaluation.

Wraps Ragas (faithfulness / answer_relevancy / context_precision). The
heavy deps live behind a lazy import and raise EvalDependenciesNotInstalled
with a clean install hint when missing, so the SDK module imports fine
without ``aigovkit[evals]`` installed.
"""

from __future__ import annotations

import asyncio
import os
from statistics import mean

from .errors import EvalDependenciesNotInstalled, NoLLMConfigured

METRIC_NAMES = ("faithfulness", "answer_relevancy", "context_precision")
REQUIRED_CASE_KEYS = ("query", "response", "contexts")


def _check_provider_keys() -> tuple[str, str]:
    anthropic_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not anthropic_key and not openai_key:
        raise NoLLMConfigured(
            "rag() requires an LLM provider key. "
            "Set ANTHROPIC_API_KEY or OPENAI_API_KEY in the environment."
        )
    if not openai_key:
        raise NoLLMConfigured(
            "rag() needs OPENAI_API_KEY for the Ragas embedder "
            "(Anthropic has no public embeddings endpoint). Set OPENAI_API_KEY "
            "alongside ANTHROPIC_API_KEY."
        )
    return anthropic_key, openai_key


def _validate_cases(cases: list[dict]) -> None:
    for i, c in enumerate(cases):
        missing = [k for k in REQUIRED_CASE_KEYS if k not in c]
        if missing:
            raise ValueError(f"case {i} is missing required key(s): {missing}")
        if not isinstance(c["contexts"], list):
            raise ValueError(
                f"case {i} 'contexts' must be a list[str], got {type(c['contexts']).__name__}"
            )


def _run_ragas(cases: list[dict]) -> list[dict[str, float]]:
    try:
        from datasets import Dataset  # noqa: WPS433
        from ragas import evaluate as ragas_evaluate  # noqa: WPS433
        from ragas.metrics import (  # noqa: WPS433
            answer_relevancy,
            context_precision,
            faithfulness,
        )
        from langchain_openai import OpenAIEmbeddings  # noqa: WPS433
    except ModuleNotFoundError as exc:
        raise EvalDependenciesNotInstalled(
            "RAG evaluation requires: pip install aigovkit[evals] "
            f"(missing module: {exc.name})"
        ) from exc

    anthropic_key, openai_key = _check_provider_keys()
    embeddings = OpenAIEmbeddings(api_key=openai_key, model="text-embedding-3-small")
    if anthropic_key:
        from langchain_anthropic import ChatAnthropic  # noqa: WPS433
        llm = ChatAnthropic(model="claude-haiku-4-5", api_key=anthropic_key, temperature=0)
    else:
        from langchain_openai import ChatOpenAI  # noqa: WPS433
        llm = ChatOpenAI(model="gpt-4o-mini", api_key=openai_key, temperature=0)

    dataset_dict = {
        "question":  [c["query"]    for c in cases],
        "answer":    [c["response"] for c in cases],
        "contexts":  [list(c["contexts"]) for c in cases],
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


async def _rag_async(cases: list[dict], threshold: float) -> dict:
    if not cases:
        return _empty_summary(threshold)
    _validate_cases(cases)
    # Fail fast on missing deps BEFORE spinning up the thread.
    try:
        # Just trigger the import paths so the friendly error surfaces here
        # rather than inside the executor (better stack trace for the user).
        import datasets  # noqa: F401, WPS433
        import ragas     # noqa: F401, WPS433
    except ModuleNotFoundError as exc:
        raise EvalDependenciesNotInstalled(
            "RAG evaluation requires: pip install aigovkit[evals] "
            f"(missing module: {exc.name})"
        ) from exc

    per_case = await asyncio.to_thread(_run_ragas, cases)
    out_cases = []
    for i, scores in enumerate(per_case):
        case_passed = bool(scores) and all(v >= threshold for v in scores.values())
        out_cases.append({
            "index": i,
            "query": cases[i]["query"],
            "scores": scores,
            "passed": case_passed,
        })
    agg = {}
    for name in METRIC_NAMES:
        xs = [c["scores"][name] for c in out_cases if name in c["scores"]]
        if xs:
            agg[name] = mean(xs)
    passed = sum(1 for c in out_cases if c["passed"])
    total = len(out_cases)
    return {
        "per_case": out_cases,
        "summary": {
            "total_cases": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": passed / total if total else 0.0,
            "threshold": threshold,
            "metrics": agg,
        },
    }


def _empty_summary(threshold: float) -> dict:
    return {
        "per_case": [],
        "summary": {
            "total_cases": 0, "passed": 0, "failed": 0, "pass_rate": 0.0,
            "threshold": threshold, "metrics": {},
        },
    }
