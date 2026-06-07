"""Local-mode judge() tests — the LLM call (`_call_judge`) is monkeypatched
so the suite never touches the network or needs a real API key. The env
fixture is per-test so the no-key test can wipe both keys."""

import asyncio
import json

import pytest

from vigilai.evals import (
    NoLLMConfigured,
    Rubric,
    RubricError,
    judge,
    parse_rubric,
)
from vigilai.evals import _judge as judge_mod


VALID_YAML = """
name: "Support quality"
criteria:
  - name: tone
    description: "Polite and professional"
    scale: 5
  - name: helpfulness
    description: "Addresses the user's need"
    scale: 5
pass_threshold: 3.5
"""

VALID_RESPONSE = json.dumps({
    "scores": {
        "tone": {"score": 5, "rationale": "Warm throughout."},
        "helpfulness": {"score": 4, "rationale": "Directly addresses the question."},
    }
})


# ---------------------------------------------------------------------------
# Rubric parsing
# ---------------------------------------------------------------------------


def test_parse_yaml_rubric():
    r = parse_rubric(VALID_YAML)
    assert isinstance(r, Rubric)
    assert r.name == "Support quality"
    assert len(r.criteria) == 2
    assert r.criteria[0].name == "tone"
    assert r.pass_threshold == 3.5


def test_parse_dict_rubric():
    r = parse_rubric({
        "name": "x",
        "criteria": [{"name": "a", "description": "b", "scale": 3}],
        "pass_threshold": 2.0,
    })
    assert r.name == "x"
    assert r.criteria[0].scale == 3


def test_parse_rubric_passthrough():
    r = parse_rubric(VALID_YAML)
    assert parse_rubric(r) is r  # Rubric in → Rubric out


def test_malformed_yaml_raises():
    bad = "name: foo\ncriteria:\n  - description: missing-name\n    scale: 5\npass_threshold: 3\n"
    with pytest.raises(RubricError):
        parse_rubric(bad)


def test_empty_yaml_raises():
    with pytest.raises(RubricError, match="empty"):
        parse_rubric("")


def test_scale_out_of_bounds_raises():
    with pytest.raises(RubricError, match="scale"):
        parse_rubric({
            "name": "x",
            "criteria": [{"name": "a", "description": "b", "scale": 99}],
            "pass_threshold": 2.0,
        })


def test_unsupported_rubric_type_raises():
    with pytest.raises(RubricError, match="str / dict / Rubric"):
        parse_rubric(42)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Scoring with mocked LLM
# ---------------------------------------------------------------------------


@pytest.fixture
def env_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_valid_response_produces_scores(env_anthropic, monkeypatch):
    async def fake(prompt, timeout=None):
        return VALID_RESPONSE

    monkeypatch.setattr(judge_mod, "_call_judge", fake)
    out = judge(
        cases=[{"input": "Q?", "output": "A."}],
        rubric=VALID_YAML,
    )
    case = out["per_case"][0]
    assert case["scores"]["tone"]["score"] == 5
    assert case["mean_score"] == pytest.approx(4.5)
    assert case["passed"] is True
    assert out["summary"]["passed"] == 1
    assert out["summary"]["errored"] == 0
    assert out["summary"]["criteria_means"]["tone"] == 5


def test_threshold_override(env_anthropic, monkeypatch):
    threes = json.dumps({
        "scores": {
            "tone": {"score": 3, "rationale": "ok"},
            "helpfulness": {"score": 3, "rationale": "ok"},
        }
    })

    async def fake(prompt, timeout=None):
        return threes

    monkeypatch.setattr(judge_mod, "_call_judge", fake)

    # default rubric threshold 3.5 → 3.0 fails
    strict = judge([{"input": "x", "output": "y"}], rubric=VALID_YAML)
    assert strict["per_case"][0]["passed"] is False

    # explicit override to 2.5 → 3.0 passes
    lenient = judge([{"input": "x", "output": "y"}], rubric=VALID_YAML, threshold=2.5)
    assert lenient["per_case"][0]["passed"] is True


def test_garbage_response_errors_case_run_continues(env_anthropic, monkeypatch):
    responses = [VALID_RESPONSE, "not json at all", VALID_RESPONSE]
    counter = {"n": 0}

    async def fake(prompt, timeout=None):
        i = counter["n"]; counter["n"] += 1
        return responses[i]

    monkeypatch.setattr(judge_mod, "_call_judge", fake)
    out = judge(
        cases=[{"input": str(i), "output": str(i)} for i in range(3)],
        rubric=VALID_YAML,
    )
    assert out["summary"]["total_cases"] == 3
    assert out["summary"]["passed"] == 2
    assert out["summary"]["errored"] == 1
    bad = next(c for c in out["per_case"] if c.get("error"))
    assert "parse failed" in bad["error"]


def test_code_fence_wrapped_response_parses(env_anthropic, monkeypatch):
    fenced = f"Sure:\n```json\n{VALID_RESPONSE}\n```\n"

    async def fake(prompt, timeout=None):
        return fenced

    monkeypatch.setattr(judge_mod, "_call_judge", fake)
    out = judge([{"input": "x", "output": "y"}], rubric=VALID_YAML)
    assert out["per_case"][0]["passed"] is True


def test_concurrency_semaphore_is_respected(env_anthropic, monkeypatch):
    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def fake(prompt, timeout=None):
        nonlocal in_flight, max_in_flight
        async with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.04)
        async with lock:
            in_flight -= 1
        return VALID_RESPONSE

    monkeypatch.setattr(judge_mod, "_call_judge", fake)
    out = judge(
        cases=[{"input": str(i), "output": str(i)} for i in range(10)],
        rubric=VALID_YAML,
        concurrency=3,
    )
    assert max_in_flight <= 3
    assert max_in_flight >= 2
    assert out["summary"]["total_cases"] == 10


def test_empty_cases(env_anthropic):
    out = judge(cases=[], rubric=VALID_YAML)
    assert out["per_case"] == []
    assert out["summary"]["total_cases"] == 0


# ---------------------------------------------------------------------------
# No-key path
# ---------------------------------------------------------------------------


def test_no_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(NoLLMConfigured, match="judge"):
        judge(cases=[{"input": "x", "output": "y"}], rubric=VALID_YAML)
