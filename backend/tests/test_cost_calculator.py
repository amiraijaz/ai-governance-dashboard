"""Pure unit tests for the cost calculator — no HTTP.

Exercises the model-name normalization (exact / date-stripped / lowercased)
and the unknown-model fallback. Uses the test DB session directly with the
seeded pricing fixture.
"""

import pytest

from services.cost_calculator import _candidate_keys, get_cost_result


# ---------------------------------------------------------------------------
# Normalization helper (pure, no DB)
# ---------------------------------------------------------------------------


def test_candidate_keys_exact_only():
    assert _candidate_keys("claude-haiku-4-5") == ["claude-haiku-4-5"]


def test_candidate_keys_strips_date_suffix():
    keys = _candidate_keys("claude-haiku-4-5-20251001")
    assert "claude-haiku-4-5-20251001" in keys
    assert "claude-haiku-4-5" in keys
    assert keys.index("claude-haiku-4-5-20251001") < keys.index("claude-haiku-4-5")


def test_candidate_keys_lowercases():
    keys = _candidate_keys("CLAUDE-Haiku-4-5")
    assert "claude-haiku-4-5" in keys


def test_candidate_keys_combines_date_strip_and_lowercase():
    keys = _candidate_keys("Claude-Sonnet-4-5-20251115")
    # Both stripped variants should be present.
    assert "claude-sonnet-4-5" in keys
    # No duplicates.
    assert len(keys) == len(set(keys))


def test_candidate_keys_strips_whitespace():
    assert _candidate_keys("  gpt-4o  ") == ["gpt-4o"]


# ---------------------------------------------------------------------------
# DB-backed cost lookup
# ---------------------------------------------------------------------------


async def test_exact_match_returns_correct_cost(seeded_pricing):
    # gpt-4o: prompt 0.005/1k, completion 0.015/1k
    # 2000 prompt + 1000 completion → 0.005*2 + 0.015*1 = 0.025
    result = await get_cost_result(seeded_pricing, "gpt-4o", 2000, 1000)
    assert result.matched_key == "gpt-4o"
    assert result.cost == pytest.approx(0.025, rel=1e-9)


async def test_date_suffix_normalization_finds_pricing(seeded_pricing):
    """A model name with a YYYYMMDD suffix should fall back to the
    stripped key in the pricing table."""
    result = await get_cost_result(
        seeded_pricing, "claude-haiku-4-5-20251001", 1000, 500
    )
    assert result.matched_key == "claude-haiku-4-5"
    # 0.0008 + 0.004*0.5 = 0.0028
    assert result.cost == pytest.approx(0.0028, rel=1e-9)


async def test_lowercase_normalization(seeded_pricing):
    """A mixed-case model name should match the lowercase pricing key."""
    result = await get_cost_result(seeded_pricing, "GPT-4o", 1000, 0)
    assert result.matched_key == "gpt-4o"
    assert result.cost == pytest.approx(0.005, rel=1e-9)


async def test_whitespace_stripped(seeded_pricing):
    result = await get_cost_result(seeded_pricing, "  gpt-4o-mini  ", 1000, 1000)
    assert result.matched_key == "gpt-4o-mini"
    # 0.00015 + 0.0006 = 0.00075
    assert result.cost == pytest.approx(0.00075, rel=1e-9)


async def test_unknown_model_returns_zero_cost_and_no_match(seeded_pricing):
    result = await get_cost_result(seeded_pricing, "made-up-model-2099", 1000, 500)
    assert result.matched_key is None
    assert result.cost == 0.0


async def test_zero_tokens_returns_zero_cost(seeded_pricing):
    result = await get_cost_result(seeded_pricing, "gpt-4o", 0, 0)
    assert result.matched_key == "gpt-4o"
    assert result.cost == 0.0
