import re
import sys
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import ModelPricing

_DATE_SUFFIX = re.compile(r"-\d{8}$")


def _candidate_keys(model: str) -> list[str]:
    raw = model.strip()
    candidates = [raw]
    no_date = _DATE_SUFFIX.sub("", raw)
    if no_date != raw:
        candidates.append(no_date)
    candidates.append(raw.lower())
    no_date_lower = _DATE_SUFFIX.sub("", raw.lower())
    if no_date_lower not in candidates:
        candidates.append(no_date_lower)
    # de-dup preserving order
    seen, out = set(), []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


@dataclass
class CostResult:
    cost: float
    matched_key: str | None  # None means unknown model


async def get_cost_result(
    db: AsyncSession,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> CostResult:
    keys = _candidate_keys(model)
    result = await db.execute(
        select(ModelPricing).where(
            ModelPricing.model_key.in_(keys), ModelPricing.is_active.is_(True)
        )
    )
    rows = {r.model_key: r for r in result.scalars()}
    # honour candidate ordering: exact > stripped-date > lowercased
    for key in keys:
        if key in rows:
            row = rows[key]
            cost = (Decimal(prompt_tokens) / 1000) * row.prompt_cost_per_1k + (
                Decimal(completion_tokens) / 1000
            ) * row.completion_cost_per_1k
            return CostResult(cost=float(cost), matched_key=row.model_key)

    print(f"[cost_calculator] unknown model '{model}'", file=sys.stderr)
    return CostResult(cost=0.0, matched_key=None)


async def get_cost(
    db: AsyncSession, model: str, prompt_tokens: int, completion_tokens: int
) -> float:
    return (await get_cost_result(db, model, prompt_tokens, completion_tokens)).cost
