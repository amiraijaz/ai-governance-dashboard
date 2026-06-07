"""LLM-as-judge evaluation driven by user-defined YAML rubrics.

A rubric defines named criteria (each with a 1..N scale and a description)
plus an aggregate ``pass_threshold`` applied to the mean score per case.
The judge LLM is called once per case with strict-JSON instructions; per-case
parse failures mark THAT case as errored without breaking the run.

Design notes
------------
* No langchain / no ragas. The judge talks to Anthropic Messages API or
  OpenAI Chat Completions directly via ``httpx`` (already a main-image
  dep). That keeps the lightweight judge runnable inside the main API
  process; the heavy RAG evaluator stays behind the requirements-evals.txt
  split.
* Concurrency is bounded by an ``asyncio.Semaphore`` so a 50-case run does
  not fire 50 simultaneous provider requests.
* JSON extraction is defensive: literal first, then code-fence-stripped,
  then "first ``{`` to last ``}``". A case whose response cannot be parsed
  is marked errored and the remaining cases continue.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from statistics import mean
from typing import Optional

import httpx
import yaml
from pydantic import BaseModel, Field, ValidationError

from .rag_evaluator import NoLLMConfigured

DEFAULT_CONCURRENCY = 5
DEFAULT_JUDGE_TIMEOUT_S = 30.0

# ---------------------------------------------------------------------------
# Rubric schema
# ---------------------------------------------------------------------------


class RubricCriterion(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    scale: int = Field(default=5, ge=2, le=10)


class Rubric(BaseModel):
    name: str = Field(min_length=1)
    criteria: list[RubricCriterion] = Field(min_length=1)
    pass_threshold: float = Field(ge=0)


class RubricError(ValueError):
    """Raised when a rubric YAML is malformed or fails structural validation."""


# ---------------------------------------------------------------------------
# Robust JSON extraction
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _extract_json(text: str) -> dict:
    """Best-effort: try literal, then strip code fences, then first-``{``-to-
    last-``}`` slice. Raises ``ValueError`` on total failure."""
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
# Provider calls — direct httpx, no SDK / no langchain
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# JudgeEvaluator
# ---------------------------------------------------------------------------


class JudgeEvaluator:
    def __init__(
        self,
        concurrency: int = DEFAULT_CONCURRENCY,
        timeout_s: float = DEFAULT_JUDGE_TIMEOUT_S,
    ) -> None:
        if concurrency < 1:
            raise ValueError(f"concurrency must be >= 1, got {concurrency}")
        self.concurrency = concurrency
        self.timeout_s = timeout_s

    # ------------------------------------------------------------------
    # Rubric parsing
    # ------------------------------------------------------------------

    def parse_rubric(self, yaml_str: str) -> Rubric:
        if not yaml_str or not yaml_str.strip():
            raise RubricError("rubric YAML is empty")
        try:
            data = yaml.safe_load(yaml_str)
        except yaml.YAMLError as exc:
            raise RubricError(f"malformed YAML: {exc}") from exc
        if not isinstance(data, dict):
            raise RubricError(
                f"rubric must be a YAML mapping, got {type(data).__name__}"
            )
        try:
            return Rubric.model_validate(data)
        except ValidationError as exc:
            raise RubricError(f"invalid rubric structure: {exc}") from exc

    # ------------------------------------------------------------------
    # Provider wiring
    # ------------------------------------------------------------------

    def _check_provider_keys(self) -> tuple[str, str]:
        anthropic_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
        openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        if not anthropic_key and not openai_key:
            raise NoLLMConfigured(
                "No LLM provider configured for judge evaluation. "
                "Set ANTHROPIC_API_KEY or OPENAI_API_KEY before running an eval."
            )
        return anthropic_key, openai_key

    async def _call_judge(self, prompt: str) -> str:
        """Single judge LLM call. Anthropic preferred, OpenAI fallback.
        Tests monkeypatch this method so the real HTTP path is never hit."""
        anthropic_key, openai_key = self._check_provider_keys()
        if anthropic_key:
            return await _call_anthropic(prompt, anthropic_key, self.timeout_s)
        return await _call_openai(prompt, openai_key, self.timeout_s)

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    @staticmethod
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

    # ------------------------------------------------------------------
    # Score extraction from a parsed JSON object
    # ------------------------------------------------------------------

    @staticmethod
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
            out[c.name] = {
                "score": s,
                "rationale": str(entry.get("rationale", "")),
            }
        return out

    # ------------------------------------------------------------------
    # Per-case evaluation
    # ------------------------------------------------------------------

    async def _evaluate_case(
        self,
        case: dict,
        rubric: Rubric,
        sem: asyncio.Semaphore,
        index: int,
    ) -> dict:
        case_input = case.get("input", "")
        case_output = case.get("output", "")
        prompt = self._build_prompt(rubric, case_input, case_output)

        async with sem:
            try:
                raw = await self._call_judge(prompt)
            except NoLLMConfigured:
                # Configuration error → propagate; affects the whole run.
                raise
            except Exception as exc:  # noqa: BLE001 — any transport / 5xx
                return _errored_case(
                    index, case_input, case_output,
                    f"judge call failed: {type(exc).__name__}: {exc}",
                )

        try:
            parsed = _extract_json(raw)
            criterion_scores = self._extract_scores(parsed, rubric)
        except ValueError as exc:
            return _errored_case(
                index, case_input, case_output,
                f"judge response parse failed: {exc}",
                raw=raw,
            )

        score_values = [v["score"] for v in criterion_scores.values()]
        case_mean = mean(score_values) if score_values else None
        passed = case_mean is not None and case_mean >= rubric.pass_threshold
        return {
            "index": index,
            "input": case_input,
            "output": case_output,
            "scores": criterion_scores,
            "mean_score": case_mean,
            "passed": passed,
        }

    # ------------------------------------------------------------------
    # Public entry
    # ------------------------------------------------------------------

    async def evaluate(self, cases: list[dict], rubric: Rubric) -> dict:
        if not cases:
            return _empty_summary(rubric)

        # Pre-flight key check so we don't fire N broken calls.
        self._check_provider_keys()

        sem = asyncio.Semaphore(self.concurrency)
        results = await asyncio.gather(
            *[self._evaluate_case(c, rubric, sem, i) for i, c in enumerate(cases)]
        )

        passed = sum(1 for r in results if r["passed"])
        errored = sum(1 for r in results if r.get("error"))
        failed = len(results) - passed

        criteria_means: dict[str, float] = {}
        for c in rubric.criteria:
            xs = [
                r["scores"][c.name]["score"]
                for r in results
                if c.name in r.get("scores", {})
            ]
            if xs:
                criteria_means[c.name] = mean(xs)

        return {
            "per_case": results,
            "summary": {
                "total_cases": len(results),
                "passed": passed,
                "failed": failed,
                "errored": errored,
                "pass_rate": passed / len(results),
                "threshold": rubric.pass_threshold,
                "rubric_name": rubric.name,
                "criteria_means": criteria_means,
            },
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _errored_case(
    index: int, case_input: str, case_output: str, message: str, raw: Optional[str] = None
) -> dict:
    out = {
        "index": index,
        "input": case_input,
        "output": case_output,
        "scores": {},
        "mean_score": None,
        "passed": False,
        "error": message,
    }
    if raw is not None:
        out["raw"] = raw[:1000]
    return out


def _empty_summary(rubric: Rubric) -> dict:
    return {
        "per_case": [],
        "summary": {
            "total_cases": 0,
            "passed": 0,
            "failed": 0,
            "errored": 0,
            "pass_rate": 0.0,
            "threshold": rubric.pass_threshold,
            "rubric_name": rubric.name,
            "criteria_means": {},
        },
    }


# ---------------------------------------------------------------------------
# Package entry — mirrors evaluate_rag
# ---------------------------------------------------------------------------


async def evaluate_with_rubric(
    cases: list[dict],
    rubric_yaml: str,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> dict:
    """Convenience: parse the YAML rubric and run the judge in one shot."""
    judge = JudgeEvaluator(concurrency=concurrency)
    rubric = judge.parse_rubric(rubric_yaml)
    return await judge.evaluate(cases, rubric)
