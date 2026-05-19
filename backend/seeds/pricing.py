"""Seed/upsert model pricing rows. Run: python -m seeds.pricing"""

import asyncio
from decimal import Decimal

from sqlalchemy.dialects.postgresql import insert

from database import AsyncSessionLocal
from models import ModelPricing

PRICES = [
    ("claude-haiku-4-5",   "Anthropic", "0.0008",   "0.004"),
    ("claude-sonnet-4-5",  "Anthropic", "0.003",    "0.015"),
    ("claude-opus-4",      "Anthropic", "0.015",    "0.075"),
    ("claude-3-5-sonnet",  "Anthropic", "0.003",    "0.015"),
    ("claude-3-5-haiku",   "Anthropic", "0.0008",   "0.004"),
    ("gpt-4o",             "OpenAI",    "0.005",    "0.015"),
    ("gpt-4o-mini",        "OpenAI",    "0.00015",  "0.0006"),
    ("gemini-1.5-pro",     "Google",    "0.00125",  "0.005"),
    ("gemini-1.5-flash",   "Google",    "0.000075", "0.0003"),
]


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        for model_key, provider, prompt_c, completion_c in PRICES:
            stmt = insert(ModelPricing).values(
                model_key=model_key,
                provider=provider,
                prompt_cost_per_1k=Decimal(prompt_c),
                completion_cost_per_1k=Decimal(completion_c),
                is_active=True,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["model_key"],
                set_={
                    "provider": stmt.excluded.provider,
                    "prompt_cost_per_1k": stmt.excluded.prompt_cost_per_1k,
                    "completion_cost_per_1k": stmt.excluded.completion_cost_per_1k,
                    "is_active": True,
                },
            )
            await db.execute(stmt)
        await db.commit()
        print(f"upserted {len(PRICES)} pricing rows")


if __name__ == "__main__":
    asyncio.run(seed())
