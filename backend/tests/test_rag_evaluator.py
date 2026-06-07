"""Unit tests for the RAG evaluator wrapper.

We never invoke real Ragas / LangChain here. ``RAGEvaluator._run_ragas`` is
the seam: a sync function returning ``list[dict[str, float]]``. Patching it
lets us exercise the validation, threshold logic, aggregation, and pass/fail
counting without any LLM keys, network, or heavy deps installed.

The no-API-key test goes through the real ``_build_llm_and_embeddings`` path
to prove ``NoLLMConfigured`` fires *before* any langchain import is attempted
(important, since langchain isn't installed in this image yet).
"""

import pytest

from services.evaluators import evaluate_rag
from services.evaluators.rag_evaluator import (
    NoLLMConfigured,
    RAGEvaluator,
    RAGEvaluatorError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cases(n: int = 2) -> list[dict]:
    return [
        {
            "query": f"What is fact #{i}?",
            "response": f"Fact #{i} is yes.",
            "contexts": [f"Document about fact #{i}.", "Irrelevant aside."],
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


async def test_empty_cases_returns_empty_summary():
    out = await evaluate_rag([])
    assert out["per_case"] == []
    assert out["summary"]["total_cases"] == 0
    assert out["summary"]["pass_rate"] == 0.0
    assert out["summary"]["metrics"] == {}


async def test_missing_required_key_raises(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    bad = [{"query": "hi", "response": "hello"}]  # no contexts
    with pytest.raises(RAGEvaluatorError, match="missing required key"):
        await evaluate_rag(bad)


async def test_contexts_must_be_a_list(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    bad = [{"query": "hi", "response": "hello", "contexts": "not a list"}]
    with pytest.raises(RAGEvaluatorError, match="must be a list"):
        await evaluate_rag(bad)


def test_threshold_out_of_range_raises():
    with pytest.raises(ValueError):
        RAGEvaluator(threshold=1.5)
    with pytest.raises(ValueError):
        RAGEvaluator(threshold=-0.1)


# ---------------------------------------------------------------------------
# Provider-key handling — exercises the real _build_llm_and_embeddings
# ---------------------------------------------------------------------------


async def test_no_api_key_raises_clear_error(monkeypatch):
    """Both keys absent → NoLLMConfigured before any langchain import."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(NoLLMConfigured, match="No LLM provider configured"):
        await evaluate_rag(_make_cases(1))


async def test_anthropic_without_openai_raises_embeddings_error(monkeypatch):
    """Anthropic has no public embeddings; if only ANTHROPIC_API_KEY is set
    we still need OPENAI_API_KEY for the embedder."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(NoLLMConfigured, match="embeddings"):
        await evaluate_rag(_make_cases(1))


# ---------------------------------------------------------------------------
# Aggregation + threshold pass/fail — _run_ragas patched
# ---------------------------------------------------------------------------


async def test_all_cases_pass_when_scores_above_threshold(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")

    def fake_run(self, cases):
        return [
            {"faithfulness": 0.9, "answer_relevancy": 0.85, "context_precision": 0.8},
            {"faithfulness": 0.95, "answer_relevancy": 0.9, "context_precision": 0.92},
        ]

    monkeypatch.setattr(RAGEvaluator, "_run_ragas", fake_run)

    out = await evaluate_rag(_make_cases(2), threshold=0.7)
    assert out["summary"]["total_cases"] == 2
    assert out["summary"]["passed"] == 2
    assert out["summary"]["failed"] == 0
    assert out["summary"]["pass_rate"] == 1.0
    assert out["summary"]["threshold"] == 0.7
    assert out["summary"]["metrics"]["faithfulness"] == pytest.approx(0.925)
    assert out["summary"]["metrics"]["answer_relevancy"] == pytest.approx(0.875)
    assert out["summary"]["metrics"]["context_precision"] == pytest.approx(0.86)
    assert all(c["passed"] for c in out["per_case"])
    # Each per-case record carries query + scores + the pass flag.
    assert out["per_case"][0]["query"] == "What is fact #0?"
    assert set(out["per_case"][0]["scores"]) == {
        "faithfulness", "answer_relevancy", "context_precision"
    }


async def test_case_fails_when_any_metric_below_threshold(monkeypatch):
    """Pass requires ALL metrics >= threshold — a single low score fails."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")

    def fake_run(self, cases):
        return [
            # case 0: borderline pass
            {"faithfulness": 0.7, "answer_relevancy": 0.8, "context_precision": 0.75},
            # case 1: faithfulness sinks it
            {"faithfulness": 0.6, "answer_relevancy": 0.9, "context_precision": 0.95},
            # case 2: all fail
            {"faithfulness": 0.3, "answer_relevancy": 0.4, "context_precision": 0.5},
        ]

    monkeypatch.setattr(RAGEvaluator, "_run_ragas", fake_run)

    out = await evaluate_rag(_make_cases(3), threshold=0.7)
    assert out["summary"]["passed"] == 1
    assert out["summary"]["failed"] == 2
    assert out["summary"]["pass_rate"] == pytest.approx(1 / 3)
    assert [c["passed"] for c in out["per_case"]] == [True, False, False]


async def test_threshold_is_honored(monkeypatch):
    """Same scores, different threshold → different pass count."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")

    def fake_run(self, cases):
        return [
            {"faithfulness": 0.75, "answer_relevancy": 0.75, "context_precision": 0.75},
            {"faithfulness": 0.85, "answer_relevancy": 0.85, "context_precision": 0.85},
        ]

    monkeypatch.setattr(RAGEvaluator, "_run_ragas", fake_run)

    lenient = await evaluate_rag(_make_cases(2), threshold=0.7)
    strict = await evaluate_rag(_make_cases(2), threshold=0.8)
    assert lenient["summary"]["passed"] == 2
    assert strict["summary"]["passed"] == 1


async def test_empty_per_case_scores_count_as_failed(monkeypatch):
    """If Ragas returns an empty score dict for a case (e.g. a metric failed
    silently and got skipped), that case must NOT count as passed."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")

    def fake_run(self, cases):
        return [{}, {"faithfulness": 0.9, "answer_relevancy": 0.9, "context_precision": 0.9}]

    monkeypatch.setattr(RAGEvaluator, "_run_ragas", fake_run)

    out = await evaluate_rag(_make_cases(2), threshold=0.7)
    assert out["per_case"][0]["passed"] is False
    assert out["per_case"][1]["passed"] is True


# ---------------------------------------------------------------------------
# Input → Ragas dataset shape
# ---------------------------------------------------------------------------


async def test_run_ragas_receives_normalized_cases(monkeypatch):
    """Confirm the wrapper passes through the raw cases as-is to _run_ragas.
    The Ragas dataset construction happens inside _run_ragas (patched here),
    so the wrapper's contract is just 'forward the case list intact'."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    seen: dict = {}

    def fake_run(self, cases):
        seen["cases"] = cases
        return [{"faithfulness": 0.9, "answer_relevancy": 0.9, "context_precision": 0.9}]

    monkeypatch.setattr(RAGEvaluator, "_run_ragas", fake_run)

    cases = [
        {
            "query": "Q1",
            "response": "A1",
            "contexts": ["c1a", "c1b"],
            "ground_truth": "GT1",
        }
    ]
    await evaluate_rag(cases)
    assert seen["cases"] == cases  # not mutated, not re-shaped
