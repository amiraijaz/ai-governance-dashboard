"""Judge evaluator tests.

The real LLM call (``JudgeEvaluator._call_judge``) is monkeypatched in
every test that needs scoring — no network, no provider keys touched.
The rubric-parsing tests do not touch the LLM at all.
"""

import asyncio
import json

import pytest

from services.evaluators import (
    JudgeEvaluator,
    NoLLMConfigured,
    Rubric,
    RubricError,
    evaluate_with_rubric,
)


VALID_YAML = """
name: "Support quality"
criteria:
  - name: professional_tone
    description: "Response maintains a professional, courteous tone"
    scale: 5
  - name: factual_accuracy
    description: "Claims are accurate and not fabricated"
    scale: 5
  - name: helpfulness
    description: "Response actually addresses the user's need"
    scale: 5
pass_threshold: 3.5
"""

VALID_JUDGE_RESPONSE = json.dumps({
    "scores": {
        "professional_tone": {"score": 5, "rationale": "Polite throughout."},
        "factual_accuracy": {"score": 4, "rationale": "All claims supported."},
        "helpfulness": {"score": 3, "rationale": "Mostly addresses the question."},
    }
})


# ---------------------------------------------------------------------------
# Rubric parsing
# ---------------------------------------------------------------------------


def test_valid_rubric_parses():
    rubric = JudgeEvaluator().parse_rubric(VALID_YAML)
    assert isinstance(rubric, Rubric)
    assert rubric.name == "Support quality"
    assert len(rubric.criteria) == 3
    assert rubric.criteria[0].name == "professional_tone"
    assert rubric.criteria[0].scale == 5
    assert rubric.pass_threshold == 3.5


def test_empty_yaml_raises():
    with pytest.raises(RubricError, match="empty"):
        JudgeEvaluator().parse_rubric("")


def test_malformed_yaml_raises():
    bad = "name: foo\ncriteria:\n  - name: x\n    description: [\n"  # unbalanced
    with pytest.raises(RubricError, match="malformed YAML"):
        JudgeEvaluator().parse_rubric(bad)


def test_top_level_must_be_mapping():
    with pytest.raises(RubricError, match="mapping"):
        JudgeEvaluator().parse_rubric("- not\n- a\n- mapping\n")


def test_missing_required_fields_raises():
    # Has `name`, missing `criteria` and `pass_threshold`.
    with pytest.raises(RubricError, match="invalid rubric structure"):
        JudgeEvaluator().parse_rubric("name: foo\n")


def test_scale_out_of_bounds_raises():
    bad = VALID_YAML.replace("scale: 5", "scale: 99")
    with pytest.raises(RubricError, match="invalid rubric structure"):
        JudgeEvaluator().parse_rubric(bad)


# ---------------------------------------------------------------------------
# Mocked LLM scoring
# ---------------------------------------------------------------------------


@pytest.fixture
def env_anthropic(monkeypatch):
    """Pre-flight passes; the actual LLM call is mocked per-test."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


async def test_valid_response_produces_scores(env_anthropic, monkeypatch):
    async def fake_call(self, prompt):
        return VALID_JUDGE_RESPONSE

    monkeypatch.setattr(JudgeEvaluator, "_call_judge", fake_call)

    out = await evaluate_with_rubric(
        cases=[{"input": "Q?", "output": "A."}],
        rubric_yaml=VALID_YAML,
    )
    assert len(out["per_case"]) == 1
    case = out["per_case"][0]
    assert case["scores"]["professional_tone"]["score"] == 5
    assert case["scores"]["helpfulness"]["rationale"]
    assert case["mean_score"] == pytest.approx(4.0)  # (5+4+3)/3
    assert case["passed"] is True                    # 4.0 >= 3.5
    assert "error" not in case
    assert out["summary"]["passed"] == 1
    assert out["summary"]["errored"] == 0
    assert out["summary"]["pass_rate"] == 1.0
    assert out["summary"]["criteria_means"]["professional_tone"] == 5
    assert out["summary"]["criteria_means"]["helpfulness"] == 3


async def test_response_wrapped_in_code_fence_is_parsed(env_anthropic, monkeypatch):
    fenced = f"Sure, here you go:\n```json\n{VALID_JUDGE_RESPONSE}\n```\n"

    async def fake_call(self, prompt):
        return fenced

    monkeypatch.setattr(JudgeEvaluator, "_call_judge", fake_call)

    out = await evaluate_with_rubric(
        cases=[{"input": "x", "output": "y"}],
        rubric_yaml=VALID_YAML,
    )
    assert out["per_case"][0]["passed"] is True
    assert out["per_case"][0]["mean_score"] == pytest.approx(4.0)


async def test_garbage_response_errors_case_run_continues(env_anthropic, monkeypatch):
    """One garbage response marks that case errored; other cases still score."""
    responses = [VALID_JUDGE_RESPONSE, "totally not json at all, just words", VALID_JUDGE_RESPONSE]
    counter = {"n": 0}

    async def fake_call(self, prompt):
        i = counter["n"]
        counter["n"] += 1
        return responses[i]

    monkeypatch.setattr(JudgeEvaluator, "_call_judge", fake_call)

    out = await evaluate_with_rubric(
        cases=[
            {"input": "1", "output": "a"},
            {"input": "2", "output": "b"},
            {"input": "3", "output": "c"},
        ],
        rubric_yaml=VALID_YAML,
    )
    assert out["summary"]["total_cases"] == 3
    assert out["summary"]["passed"] == 2
    assert out["summary"]["errored"] == 1
    assert out["summary"]["failed"] == 1  # the errored one counts as failed too
    bad = next(c for c in out["per_case"] if c.get("error"))
    assert "parse failed" in bad["error"]
    assert bad["mean_score"] is None
    # Aggregate criteria_means only averages over non-errored cases.
    assert out["summary"]["criteria_means"]["professional_tone"] == 5  # (5+5)/2


async def test_missing_criterion_in_response_errors_case(env_anthropic, monkeypatch):
    """Judge omits a criterion → parse extraction raises → case errored."""
    incomplete = json.dumps({
        "scores": {
            "professional_tone": {"score": 5, "rationale": "ok"},
            # factual_accuracy missing
            "helpfulness": {"score": 4, "rationale": "ok"},
        }
    })

    async def fake_call(self, prompt):
        return incomplete

    monkeypatch.setattr(JudgeEvaluator, "_call_judge", fake_call)

    out = await evaluate_with_rubric(
        cases=[{"input": "x", "output": "y"}],
        rubric_yaml=VALID_YAML,
    )
    assert out["per_case"][0].get("error")
    assert "factual_accuracy" in out["per_case"][0]["error"]


async def test_out_of_range_score_errors_case(env_anthropic, monkeypatch):
    over = json.dumps({
        "scores": {
            "professional_tone": {"score": 7, "rationale": "ok"},  # scale is 5
            "factual_accuracy": {"score": 5, "rationale": "ok"},
            "helpfulness": {"score": 5, "rationale": "ok"},
        }
    })

    async def fake_call(self, prompt):
        return over

    monkeypatch.setattr(JudgeEvaluator, "_call_judge", fake_call)
    out = await evaluate_with_rubric(
        cases=[{"input": "x", "output": "y"}],
        rubric_yaml=VALID_YAML,
    )
    assert out["per_case"][0].get("error")
    assert "out of range" in out["per_case"][0]["error"]


async def test_pass_threshold_logic(env_anthropic, monkeypatch):
    """Same scores, different rubric thresholds → different pass counts."""
    threes = json.dumps({
        "scores": {
            "professional_tone": {"score": 3, "rationale": "ok"},
            "factual_accuracy": {"score": 3, "rationale": "ok"},
            "helpfulness": {"score": 3, "rationale": "ok"},
        }
    })

    async def fake_call(self, prompt):
        return threes

    monkeypatch.setattr(JudgeEvaluator, "_call_judge", fake_call)

    # Threshold 3.5 → mean 3.0 fails.
    strict = await evaluate_with_rubric(
        cases=[{"input": "x", "output": "y"}],
        rubric_yaml=VALID_YAML,
    )
    assert strict["per_case"][0]["passed"] is False
    assert strict["per_case"][0]["mean_score"] == 3.0

    # Threshold 2.5 → mean 3.0 passes.
    lenient_yaml = VALID_YAML.replace("pass_threshold: 3.5", "pass_threshold: 2.5")
    lenient = await evaluate_with_rubric(
        cases=[{"input": "x", "output": "y"}],
        rubric_yaml=lenient_yaml,
    )
    assert lenient["per_case"][0]["passed"] is True


async def test_concurrency_semaphore_is_respected(env_anthropic, monkeypatch):
    """With concurrency=3 and 10 cases, the judge call must never have more
    than 3 in-flight at once. Verifies the semaphore is actually wired up."""
    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def fake_call(self, prompt):
        nonlocal in_flight, max_in_flight
        async with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.05)   # hold so concurrent calls overlap
        async with lock:
            in_flight -= 1
        return VALID_JUDGE_RESPONSE

    monkeypatch.setattr(JudgeEvaluator, "_call_judge", fake_call)

    judge = JudgeEvaluator(concurrency=3)
    rubric = judge.parse_rubric(VALID_YAML)
    cases = [{"input": f"i{n}", "output": f"o{n}"} for n in range(10)]
    out = await judge.evaluate(cases, rubric)

    assert max_in_flight <= 3, f"semaphore breached: {max_in_flight} > 3"
    assert max_in_flight >= 2, "no concurrency observed at all — semaphore wiring may be broken"
    assert out["summary"]["passed"] == 10


async def test_empty_cases_returns_empty_summary(env_anthropic):
    out = await evaluate_with_rubric(cases=[], rubric_yaml=VALID_YAML)
    assert out["per_case"] == []
    assert out["summary"]["total_cases"] == 0
    assert out["summary"]["pass_rate"] == 0.0
    assert out["summary"]["rubric_name"] == "Support quality"


# ---------------------------------------------------------------------------
# No-key path
# ---------------------------------------------------------------------------


async def test_no_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(NoLLMConfigured, match="No LLM provider"):
        await evaluate_with_rubric(
            cases=[{"input": "x", "output": "y"}],
            rubric_yaml=VALID_YAML,
        )


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_concurrency_below_one_raises():
    with pytest.raises(ValueError, match="concurrency"):
        JudgeEvaluator(concurrency=0)
