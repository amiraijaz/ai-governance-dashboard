"""LLM-as-judge — pure-httpx implementation, no langchain / no ragas.

Mirrors the backend's services/evaluators/judge_evaluator.py:
* YAML rubrics (dict or yaml string)
* per-criterion 1..scale scoring with a one-sentence rationale
* strict-JSON parsing with code-fence stripping and first-{-to-last-} fallback
* bounded concurrency via asyncio.Semaphore
* per-case error isolation — one bad response marks that case errored,
  the run continues
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from statistics import mean
from typing import Any, Optional, Union

import httpx
import yaml

from .errors import NoLLMConfigured, RubricError

DEFAULT_CONCURRENCY = 5
DEFAULT_JUDGE_TIMEOUT_S = 30.0
DEFAULT_PASS_THRESHOLD = 3.5


# ---------------------------------------------------------------------------
# Rubric — dataclasses rather than pydantic so the SDK stays dep-light.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RubricCriterion:
    name: str
    description: str
    scale: int = 5


@dataclass(frozen=True)
class Rubric:
    name: str
    criteria: list[RubricCriterion]
    pass_threshold: float = DEFAULT_PASS_THRESHOLD


def parse_rubric(rubric: Union[str, dict, Rubric]) -> Rubric:
    """Accept a YAML string, a plain dict, or a Rubric instance."""
    if isinstance(rubric, Rubric):
        return rubric
    if isinstance(rubric, str):
        if not rubric.strip():
            raise RubricError("rubric YAML is empty")
        try:
            data = yaml.safe_load(rubric)
        except yaml.YAMLError as exc:
            raise RubricError(f"malformed YAML: {exc}") from exc
        if not isinstance(data, dict):
            raise RubricError(
                f"rubric must be a YAML mapping, got {type(data).__name__}"
            )
    elif isinstance(rubric, dict):
        data = rubric
    else:
        raise RubricError(
            f"rubric must be a str / dict / Rubric, got {type(rubric).__name__}"
        )

    name = data.get("name")
    raw_criteria = data.get("criteria")
    pass_threshold = data.get("pass_threshold", DEFAULT_PASS_THRESHOLD)
    if not isinstance(name, str) or not name.strip():
        raise RubricError("rubric.name is required and must be a non-empty string")
    if not isinstance(raw_criteria, list) or not raw_criteria:
        raise RubricError("rubric.criteria must be a non-empty list")
    try:
        threshold = float(pass_threshold)
    except (TypeError, ValueError) as exc:
        raise RubricError("rubric.pass_threshold must be a number") from exc

    criteria: list[RubricCriterion] = []
    for i, c in enumerate(raw_criteria):
        if not isinstance(c, dict):
            raise RubricError(f"rubric.criteria[{i}] must be a mapping")
        cname = c.get("name")
        cdesc = c.get("description")
        cscale = c.get("scale", 5)
        if not isinstance(cname, str) or not cname.strip():
            raise RubricError(f"rubric.criteria[{i}].name is required")
        if not isinstance(cdesc, str) or not cdesc.strip():
            raise RubricError(f"rubric.criteria[{i}].description is required")
        if not isinstance(cscale, int) or cscale < 2 or cscale > 10:
            raise RubricError(
                f"rubric.criteria[{i}].scale must be an int in [2,10], got {cscale!r}"
            )
        criteria.append(RubricCriterion(name=cname, description=cdesc, scale=cscale))

    return Rubric(name=name, criteria=criteria, pass_threshold=threshold)


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _extract_json(text: str) -> dict:
    if not text or not text.strip():
        raise ValueError("empty response")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"could not parse JSON: {exc}") from exc
    raise ValueError("no JSON object found in response")


# ---------------------------------------------------------------------------
# Provider calls
# ---------------------------------------------------------------------------


def _check_provider_keys() -> tuple[str, str]:
    anthropic_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not anthropic_key and not openai_key:
        raise NoLLMConfigured(
            "judge() requires an LLM provider key. "
            "Set ANTHROPIC_API_KEY or OPENAI_API_KEY in the environment."
        )
    return anthropic_key, openai_key


async def _call_anthropic(prompt: str, api_key: str, timeout: float) -> str:
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5",
                "max_tokens": 800,
                "temperature": 0,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        r.raise_for_status()
        return r.json()["content"][0]["text"]


async def _call_openai(prompt: str, api_key: str, timeout: float) -> str:
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "content-type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "temperature": 0,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


# Module-level so tests can monkeypatch this single seam.
async def _call_judge(prompt: str, timeout: float = DEFAULT_JUDGE_TIMEOUT_S) -> str:
    anthropic_key, openai_key = _check_provider_keys()
    if anthropic_key:
        return await _call_anthropic(prompt, anthropic_key, timeout)
    return await _call_openai(prompt, openai_key, timeout)


# ---------------------------------------------------------------------------
# Prompt + parse + run
# ---------------------------------------------------------------------------


def _build_prompt(rubric: Rubric, case_input: str, case_output: str) -> str:
    crit_block = "\n".join(
        f"- {c.name} (1-{c.scale}): {c.description}" for c in rubric.criteria
    )
    json_template_inner = ",\n".join(
        f'    "{c.name}": {{"score": <integer 1-{c.scale}>, "rationale": "<one sentence>"}}'
        for c in rubric.criteria
    )
    return (
        f"You are a strict evaluator. Score the response below against the rubric.\n\n"
        f"Rubric: {rubric.name}\n"
        f"Criteria:\n{crit_block}\n\n"
        f"User input:\n{case_input}\n\n"
        f"Response to evaluate:\n{case_output}\n\n"
        f"Return ONLY valid JSON in this exact shape, no commentary, no code fences:\n"
        f"{{\n"
        f'  "scores": {{\n'
        f"{json_template_inner}\n"
        f"  }}\n"
        f"}}\n"
    )


def _extract_scores(parsed: dict, rubric: Rubric) -> dict[str, dict]:
    if not isinstance(parsed, dict) or "scores" not in parsed:
        raise ValueError("response missing top-level 'scores' object")
    scores_obj = parsed["scores"]
    if not isinstance(scores_obj, dict):
        raise ValueError("'scores' must be an object")
    out: dict[str, dict] = {}
    for c in rubric.criteria:
        entry = scores_obj.get(c.name)
        if not isinstance(entry, dict) or "score" not in entry:
            raise ValueError(f"missing or malformed score for '{c.name}'")
        try:
            s = float(entry["score"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"non-numeric score for '{c.name}'") from exc
        if not 1 <= s <= c.scale:
            raise ValueError(
                f"score for '{c.name}' out of range 1..{c.scale}: {s}"
            )
        out[c.name] = {"score": s, "rationale": str(entry.get("rationale", ""))}
    return out


async def _evaluate_case(
    case: dict, rubric: Rubric, sem: asyncio.Semaphore, index: int, timeout: float
) -> dict:
    case_input = case.get("input", "")
    case_output = case.get("output", "")
    prompt = _build_prompt(rubric, case_input, case_output)
    async with sem:
        try:
            raw = await _call_judge(prompt, timeout)
        except NoLLMConfigured:
            raise
        except Exception as exc:  # noqa: BLE001
            return _errored(index, case_input, case_output,
                            f"judge call failed: {type(exc).__name__}: {exc}")
    try:
        parsed = _extract_json(raw)
        scores = _extract_scores(parsed, rubric)
    except ValueError as exc:
        return _errored(index, case_input, case_output,
                        f"judge response parse failed: {exc}", raw=raw)
    score_values = [v["score"] for v in scores.values()]
    case_mean = mean(score_values) if score_values else None
    passed = case_mean is not None and case_mean >= rubric.pass_threshold
    return {
        "index": index,
        "input": case_input,
        "output": case_output,
        "scores": scores,
        "mean_score": case_mean,
        "passed": passed,
    }


def _errored(index, ci, co, msg, raw=None):
    out = {
        "index": index, "input": ci, "output": co, "scores": {},
        "mean_score": None, "passed": False, "error": msg,
    }
    if raw is not None:
        out["raw"] = raw[:1000]
    return out


async def _judge_async(
    cases: list[dict], rubric: Rubric, concurrency: int, timeout: float
) -> dict:
    if not cases:
        return _empty_summary(rubric)
    _check_provider_keys()  # fail fast pre-flight
    sem = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(
        *[_evaluate_case(c, rubric, sem, i, timeout) for i, c in enumerate(cases)]
    )
    passed = sum(1 for r in results if r["passed"])
    errored = sum(1 for r in results if r.get("error"))
    criteria_means = {}
    for c in rubric.criteria:
        xs = [r["scores"][c.name]["score"] for r in results if c.name in r.get("scores", {})]
        if xs:
            criteria_means[c.name] = mean(xs)
    return {
        "per_case": results,
        "summary": {
            "total_cases": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "errored": errored,
            "pass_rate": passed / len(results),
            "threshold": rubric.pass_threshold,
            "rubric_name": rubric.name,
            "criteria_means": criteria_means,
        },
    }


def _empty_summary(rubric: Rubric) -> dict:
    return {
        "per_case": [],
        "summary": {
            "total_cases": 0, "passed": 0, "failed": 0, "errored": 0,
            "pass_rate": 0.0, "threshold": rubric.pass_threshold,
            "rubric_name": rubric.name, "criteria_means": {},
        },
    }
