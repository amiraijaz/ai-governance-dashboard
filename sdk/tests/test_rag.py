"""Local-mode rag() tests — the friendly install-hint path is the one we
can guarantee in this environment (the [evals] extras aren't installed),
so that's the test that runs unconditionally. The full Ragas path needs
the optional extras + real API keys and is left to integration tier."""

import pytest

from aigovkit.evals import EvalDependenciesNotInstalled, rag


def test_rag_without_extras_raises_clean_install_hint(monkeypatch):
    """No matter what env keys are set, missing ragas/datasets must
    surface the documented install hint rather than ModuleNotFoundError."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fake")
    with pytest.raises(EvalDependenciesNotInstalled, match="aigovkit\\[evals\\]"):
        rag(cases=[{
            "query": "What is X?",
            "response": "X is foo.",
            "contexts": ["X is foo."],
        }])


def test_rag_validates_required_keys_first(monkeypatch):
    """Validation runs BEFORE the dep check so users with malformed input
    see the input error first (more actionable)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    bad = [{"query": "x", "response": "y"}]  # missing contexts
    with pytest.raises(ValueError, match="missing required key"):
        rag(cases=bad)


def test_rag_empty_cases_returns_empty_summary():
    out = rag(cases=[])
    assert out["per_case"] == []
    assert out["summary"]["total_cases"] == 0
    assert out["summary"]["threshold"] == 0.7
