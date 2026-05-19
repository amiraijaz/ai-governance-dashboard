import sys
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models import ModelPricing

LITELLM_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)

# litellm provider -> our display provider
PROVIDER_DISPLAY = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "google": "Google",
    "vertex_ai-language-models": "Google",
    "gemini": "Google",
}


async def _fetch_litellm() -> dict[str, dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(LITELLM_URL)
        r.raise_for_status()
        data = r.json()
    data.pop("sample_spec", None)
    return data


async def _upsert_provider(
    db: AsyncSession,
    data: dict[str, dict[str, Any]],
    litellm_provider: str,
    display_provider: str,
) -> int:
    """Upsert all rows for one provider. Returns row count."""
    now = datetime.now(timezone.utc)
    count = 0
    for model_key, info in data.items():
        if info.get("litellm_provider") != litellm_provider:
            continue
        in_cost = info.get("input_cost_per_token")
        out_cost = info.get("output_cost_per_token")
        if in_cost is None or out_cost is None:
            continue

        stmt = insert(ModelPricing).values(
            model_key=model_key,
            provider=display_provider,
            prompt_cost_per_1k=Decimal(str(in_cost)) * 1000,
            completion_cost_per_1k=Decimal(str(out_cost)) * 1000,
            is_active=True,
            last_synced_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["model_key"],
            set_={
                "provider": stmt.excluded.provider,
                "prompt_cost_per_1k": stmt.excluded.prompt_cost_per_1k,
                "completion_cost_per_1k": stmt.excluded.completion_cost_per_1k,
                "is_active": True,
                "last_synced_at": now,
            },
        )
        await db.execute(stmt)
        count += 1
    return count


class PricingSyncService:
    async def _sync_one(
        self,
        db: AsyncSession,
        data: dict[str, Any] | None,
        litellm_provider: str,
        display_provider: str,
    ) -> int:
        if data is None:
            data = await _fetch_litellm()
        return await _upsert_provider(db, data, litellm_provider, display_provider)

    async def sync_anthropic(
        self, db: AsyncSession, data: dict[str, Any] | None = None
    ) -> int:
        return await self._sync_one(db, data, "anthropic", "Anthropic")

    async def sync_openai(
        self, db: AsyncSession, data: dict[str, Any] | None = None
    ) -> int:
        return await self._sync_one(db, data, "openai", "OpenAI")

    async def sync_google(
        self, db: AsyncSession, data: dict[str, Any] | None = None
    ) -> int:
        # litellm splits Google across multiple provider tags; union them.
        if data is None:
            data = await _fetch_litellm()
        total = 0
        for tag in ("gemini", "vertex_ai-language-models", "google"):
            total += await _upsert_provider(db, data, tag, "Google")
        return total

    async def sync_all(self, db: AsyncSession) -> dict[str, Any]:
        errors: list[str] = []
        synced = 0
        try:
            data = await _fetch_litellm()
        except Exception as exc:
            msg = f"failed to fetch litellm catalog: {exc}"
            print(f"[pricing] {msg}", file=sys.stderr)
            return {"synced": 0, "updated": 0, "errors": [msg]}

        for name, fn in (
            ("anthropic", self.sync_anthropic),
            ("openai", self.sync_openai),
            ("google", self.sync_google),
        ):
            try:
                synced += await fn(db, data=data)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                print(f"[pricing] {name} sync failed: {exc}", file=sys.stderr)

        await db.commit()
        print(f"[pricing] synced {synced} models from litellm")
        return {"synced": synced, "updated": synced, "errors": errors}


pricing_sync_service = PricingSyncService()
