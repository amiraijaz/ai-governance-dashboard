"""Demo data for the public Vigil deployment.

Seeds the database with two demo users, five realistic models, 100 audit logs
spread across the past 30 days, and 10 safety flags in mixed review states.
The data is deterministic (fixed RNG seed) so the public URL looks the same
every time it's reseeded.

Run locally:
    docker compose exec api python seeds/demo_data.py --reset

Run on Railway:
    railway run python seeds/demo_data.py --reset

Without --reset the script refuses to overwrite existing demo rows; with
--reset it deletes only the rows tied to the demo accounts (cascades take
care of dependent audit logs and safety flags). It never touches non-demo
records.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import pathlib
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

# Make `python seeds/demo_data.py` work in addition to `python -m seeds.demo_data`.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password
from database import AsyncSessionLocal
from models import AuditLog, ModelPricing, ModelRegistry, SafetyFlag, User

# ----------------------------------------------------------------------------
# Determinism
# ----------------------------------------------------------------------------

SEED = 20251201
random.seed(SEED)

# All timestamps are anchored to "now" so the dashboard always shows
# a fresh 30-day window after each reseed.
NOW = datetime.now(timezone.utc).replace(microsecond=0)

# ----------------------------------------------------------------------------
# Demo identity
# ----------------------------------------------------------------------------

ADMIN_EMAIL = "admin@vigil.demo"
ADMIN_PASSWORD = "Vigil2025!Demo"
VIEWER_EMAIL = "viewer@vigil.demo"
VIEWER_PASSWORD = "Viewer2025!"

DEMO_ORG = "Vigil Demo Co."

# Marks every demo model so --reset can find them without name-matching.
DEMO_OWNER_EMAIL = ADMIN_EMAIL


# ----------------------------------------------------------------------------
# Model catalogue — realistic per-model token / traffic / latency profiles
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelSpec:
    name: str
    provider: str
    model_version: str
    risk_level: str
    status: str
    use_case: str
    owner_team: str
    description: str
    # Traffic share across the 100 logs (must sum to 1.0).
    traffic_share: float
    # Token ranges (min, max).
    prompt_tokens: tuple[int, int]
    completion_tokens: tuple[int, int]
    # Latency lognormal parameters tuned per archetype.
    latency_mu: float
    latency_sigma: float


MODELS: list[ModelSpec] = [
    ModelSpec(
        name="Customer Support Assistant",
        provider="Anthropic",
        model_version="claude-haiku-4-5",
        risk_level="High",
        status="Active",
        use_case="Tier-1 customer support — handles refunds, status checks, FAQs.",
        owner_team="Customer Experience",
        description=(
            "Public-facing chatbot embedded in the help centre. High risk because "
            "it talks directly to end-users about account data."
        ),
        traffic_share=0.45,
        prompt_tokens=(200, 800),
        completion_tokens=(120, 420),
        latency_mu=6.55,   # ~700ms median
        latency_sigma=0.55,
    ),
    ModelSpec(
        name="Internal Code Reviewer",
        provider="OpenAI",
        model_version="gpt-4o",
        risk_level="Medium",
        status="Active",
        use_case="Pull-request review bot — flags bugs, suggests refactors.",
        owner_team="Platform Engineering",
        description=(
            "Triggered on every PR. Sees source code but never customer data, "
            "hence Medium risk."
        ),
        traffic_share=0.20,
        prompt_tokens=(1500, 5000),
        completion_tokens=(300, 1200),
        latency_mu=6.95,   # ~1050ms median
        latency_sigma=0.60,
    ),
    ModelSpec(
        name="Contract Summariser",
        provider="Anthropic",
        model_version="claude-sonnet-4-5",
        risk_level="Critical",
        status="Active",
        use_case="Distils MSAs and DPAs into a one-page legal brief.",
        owner_team="Legal Ops",
        description=(
            "Critical risk: outputs feed directly into contract negotiations. "
            "Every response is reviewed before being acted on."
        ),
        traffic_share=0.15,
        prompt_tokens=(4000, 15000),   # high prompt — long contracts
        completion_tokens=(200, 800),
        latency_mu=7.40,   # ~1640ms median (long context)
        latency_sigma=0.55,
    ),
    ModelSpec(
        name="Marketing Copy Generator",
        provider="OpenAI",
        model_version="gpt-4o-mini",
        risk_level="Low",
        status="Active",
        use_case="Generates ad creative, social posts, newsletter blurbs.",
        owner_team="Growth Marketing",
        description=(
            "Low risk — outputs are always reviewed by a human before publication."
        ),
        traffic_share=0.15,
        prompt_tokens=(120, 450),
        completion_tokens=(450, 1500),   # high completion — long copy
        latency_mu=6.40,   # ~600ms median (smaller model)
        latency_sigma=0.50,
    ),
    ModelSpec(
        name="Knowledge Base Search",
        provider="Google",
        model_version="gemini-1.5-flash",
        risk_level="Medium",
        status="Paused",
        use_case="Semantic search over internal Confluence + Notion pages.",
        owner_team="Knowledge Management",
        description=(
            "Currently paused while we evaluate Gemini 2.0. Historical logs "
            "remain for analytics continuity."
        ),
        traffic_share=0.05,
        prompt_tokens=(300, 1200),
        completion_tokens=(50, 300),
        latency_mu=6.20,   # ~490ms median
        latency_sigma=0.45,
    ),
]

assert abs(sum(m.traffic_share for m in MODELS) - 1.0) < 1e-6


# ----------------------------------------------------------------------------
# Pricing (mirrors seeds/pricing.py — kept inline so this script is self-contained)
# ----------------------------------------------------------------------------

PRICES: dict[str, tuple[str, Decimal, Decimal]] = {
    "claude-haiku-4-5":   ("Anthropic", Decimal("0.0008"),   Decimal("0.004")),
    "claude-sonnet-4-5":  ("Anthropic", Decimal("0.003"),    Decimal("0.015")),
    "gpt-4o":             ("OpenAI",    Decimal("0.005"),    Decimal("0.015")),
    "gpt-4o-mini":        ("OpenAI",    Decimal("0.00015"),  Decimal("0.0006")),
    "gemini-1.5-flash":   ("Google",    Decimal("0.000075"), Decimal("0.0003")),
}


def compute_cost(model_version: str, prompt_tokens: int, completion_tokens: int) -> float:
    provider, prompt_c, completion_c = PRICES[model_version]
    cost = (
        (Decimal(prompt_tokens) / 1000) * prompt_c
        + (Decimal(completion_tokens) / 1000) * completion_c
    )
    # Round to 6dp so the dashboard displays cleanly.
    return float(cost.quantize(Decimal("0.000001")))


# ----------------------------------------------------------------------------
# Timestamp generator — biased toward weekday business hours
# ----------------------------------------------------------------------------


def _pick_timestamp(rng: random.Random) -> datetime:
    """Pick a moment in the past 30 days, weighted to weekday business hours."""
    while True:
        offset_minutes = rng.randint(0, 30 * 24 * 60 - 1)
        candidate = NOW - timedelta(minutes=offset_minutes)
        weight = 1.0
        # Weekends: keep ~25% of the natural rate.
        if candidate.weekday() >= 5:
            weight *= 0.25
        # Outside 09:00–18:00 UTC: keep ~30%.
        if not (9 <= candidate.hour < 18):
            weight *= 0.30
        if rng.random() < weight:
            return candidate


# ----------------------------------------------------------------------------
# Reset logic — only touches rows tied to the demo accounts
# ----------------------------------------------------------------------------


async def _wipe_demo(db: AsyncSession) -> None:
    """Delete every row created by previous runs of this script.

    Cascades:
        ModelRegistry → AuditLog → SafetyFlag    (delete models → flags gone)
        User → APIKey                            (delete users → keys gone)

    Pricing rows are left alone — they're shared with the real catalog.
    """
    await db.execute(
        delete(ModelRegistry).where(ModelRegistry.owner_email == DEMO_OWNER_EMAIL)
    )
    await db.execute(
        delete(User).where(User.email.in_([ADMIN_EMAIL, VIEWER_EMAIL]))
    )
    await db.commit()


async def _demo_rows_exist(db: AsyncSession) -> bool:
    existing = await db.scalar(
        select(User.id).where(User.email == ADMIN_EMAIL).limit(1)
    )
    return existing is not None


# ----------------------------------------------------------------------------
# Pricing upsert (so cost lookups work on a fresh DB)
# ----------------------------------------------------------------------------


async def _upsert_pricing(db: AsyncSession) -> None:
    for model_key, (provider, prompt_c, completion_c) in PRICES.items():
        stmt = pg_insert(ModelPricing).values(
            model_key=model_key,
            provider=provider,
            prompt_cost_per_1k=prompt_c,
            completion_cost_per_1k=completion_c,
            is_active=True,
            last_synced_at=NOW,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["model_key"],
            set_={
                "provider": stmt.excluded.provider,
                "prompt_cost_per_1k": stmt.excluded.prompt_cost_per_1k,
                "completion_cost_per_1k": stmt.excluded.completion_cost_per_1k,
                "is_active": True,
                "last_synced_at": NOW,
            },
        )
        await db.execute(stmt)
    await db.commit()


# ----------------------------------------------------------------------------
# Seed steps
# ----------------------------------------------------------------------------


async def _create_users(db: AsyncSession) -> tuple[User, User]:
    admin = User(
        email=ADMIN_EMAIL,
        hashed_password=hash_password(ADMIN_PASSWORD),
        role="admin",
        organisation=DEMO_ORG,
    )
    viewer = User(
        email=VIEWER_EMAIL,
        hashed_password=hash_password(VIEWER_PASSWORD),
        role="viewer",
        organisation=DEMO_ORG,
    )
    db.add_all([admin, viewer])
    await db.flush()
    return admin, viewer


async def _create_models(db: AsyncSession) -> dict[str, ModelRegistry]:
    by_version: dict[str, ModelRegistry] = {}
    for spec in MODELS:
        row = ModelRegistry(
            name=spec.name,
            provider=spec.provider,
            model_version=spec.model_version,
            use_case=spec.use_case,
            owner_team=spec.owner_team,
            owner_email=DEMO_OWNER_EMAIL,
            risk_level=spec.risk_level,
            status=spec.status,
            description=spec.description,
            deployment_date=(NOW - timedelta(days=random.randint(45, 240))).date(),
        )
        db.add(row)
        by_version[spec.model_version] = row
    await db.flush()
    return by_version


def _hash_prompt(seed: int) -> str:
    return hashlib.sha256(f"vigil-demo-prompt-{seed}".encode()).hexdigest()


def _allocate_logs_per_model(total: int, rng: random.Random) -> list[ModelSpec]:
    """Return a list of length `total` of ModelSpecs honouring traffic_share."""
    # Multinomial-ish: floor each share, then distribute leftovers by RNG.
    counts = {m.name: int(m.traffic_share * total) for m in MODELS}
    while sum(counts.values()) < total:
        counts[rng.choices(
            population=[m.name for m in MODELS],
            weights=[m.traffic_share for m in MODELS],
        )[0]] += 1
    out: list[ModelSpec] = []
    by_name = {m.name: m for m in MODELS}
    for name, c in counts.items():
        out.extend([by_name[name]] * c)
    rng.shuffle(out)
    return out


async def _create_logs(
    db: AsyncSession, models: dict[str, ModelRegistry], rng: random.Random
) -> list[AuditLog]:
    """100 audit logs spread across 30 days with realistic distributions."""
    specs = _allocate_logs_per_model(100, rng)
    logs: list[AuditLog] = []
    for i, spec in enumerate(specs):
        ts = _pick_timestamp(rng)
        prompt_tokens = rng.randint(*spec.prompt_tokens)
        completion_tokens = rng.randint(*spec.completion_tokens)

        # 95% success, 3% error, 2% timeout — but only for active models.
        # Paused model: all historical successes (no recent traffic anyway).
        if spec.status == "Active":
            roll = rng.random()
            if roll < 0.95:
                status = "success"
                latency_ms = int(rng.lognormvariate(spec.latency_mu, spec.latency_sigma))
            elif roll < 0.98:
                status = "error"
                # Errors fail fast.
                latency_ms = rng.randint(100, 600)
                completion_tokens = 0
            else:
                status = "timeout"
                latency_ms = rng.randint(8000, 15000)
                completion_tokens = 0
        else:
            status = "success"
            latency_ms = int(rng.lognormvariate(spec.latency_mu, spec.latency_sigma))

        # Clamp latency to a sane upper bound.
        latency_ms = min(latency_ms, 30_000)

        cost = (
            compute_cost(spec.model_version, prompt_tokens, completion_tokens)
            if status != "timeout"
            else 0.0
        )

        log = AuditLog(
            model_id=models[spec.model_version].id,
            timestamp=ts,
            prompt_hash=_hash_prompt(i),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_cost_usd=cost,
            latency_ms=latency_ms,
            user_id=f"user_{rng.randint(1000, 9999)}",
            session_id=f"sess_{rng.randint(100000, 999999)}",
            status=status,
            extra_metadata=(
                {"reason": "upstream_timeout"} if status == "timeout"
                else ({"reason": "rate_limited"} if status == "error" else None)
            ),
        )
        db.add(log)
        logs.append(log)
    await db.flush()
    return logs


# ----------------------------------------------------------------------------
# Safety flags
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class FlagSpec:
    flag_type: str
    severity: str
    confidence: float
    details: dict
    reviewed: bool
    review_status: Optional[str] = None
    review_notes: Optional[str] = None


# 10 flags total — 6 reviewed, 4 still in the queue.
FLAG_SPECS: list[FlagSpec] = [
    # --- PII (3 × RED, 0.88–0.95) ----------------------------------------
    FlagSpec(
        flag_type="PII_DETECTED",
        severity="RED",
        confidence=0.94,
        details={"entities": ["EMAIL_ADDRESS"], "examples": ["jordan.lee@<redacted>"]},
        reviewed=True,
        review_status="issue_found",
        review_notes=(
            "Customer email surfaced in completion. Filed CX-2841 to add output "
            "sanitiser before the response is returned to the chat widget."
        ),
    ),
    FlagSpec(
        flag_type="PII_DETECTED",
        severity="RED",
        confidence=0.91,
        details={"entities": ["PHONE_NUMBER"], "examples": ["+1-415-***-****"]},
        reviewed=True,
        review_status="escalated",
        review_notes="Escalated to legal — third occurrence this month.",
    ),
    FlagSpec(
        flag_type="PII_DETECTED",
        severity="RED",
        confidence=0.88,
        details={"entities": ["CREDIT_CARD"], "examples": ["**** **** **** 4242"]},
        reviewed=False,
    ),
    # --- TOXICITY (2 × YELLOW ~0.6, 2 × RED ~0.85) -----------------------
    FlagSpec(
        flag_type="TOXICITY",
        severity="YELLOW",
        confidence=0.61,
        details={"category": "harassment", "score": 0.61},
        reviewed=True,
        review_status="safe",
        review_notes="False positive — quoted user complaint, not generated content.",
    ),
    FlagSpec(
        flag_type="TOXICITY",
        severity="YELLOW",
        confidence=0.58,
        details={"category": "harassment", "score": 0.58},
        reviewed=False,
    ),
    FlagSpec(
        flag_type="TOXICITY",
        severity="RED",
        confidence=0.87,
        details={"category": "hate", "score": 0.87},
        reviewed=True,
        review_status="issue_found",
        review_notes="Genuine policy violation. Sample added to red-team eval set.",
    ),
    FlagSpec(
        flag_type="TOXICITY",
        severity="RED",
        confidence=0.84,
        details={"category": "violence", "score": 0.84},
        reviewed=False,
    ),
    # --- PROMPT_INJECTION (3 × YELLOW ~0.75) -----------------------------
    FlagSpec(
        flag_type="PROMPT_INJECTION",
        severity="YELLOW",
        confidence=0.78,
        details={"pattern": "ignore previous instructions"},
        reviewed=True,
        review_status="safe",
        review_notes="User pasted a Reddit prompt; model held the system prompt correctly.",
    ),
    FlagSpec(
        flag_type="PROMPT_INJECTION",
        severity="YELLOW",
        confidence=0.74,
        details={"pattern": "act as if"},
        reviewed=True,
        review_status="safe",
        review_notes="Benign role-play request, not adversarial.",
    ),
    FlagSpec(
        flag_type="PROMPT_INJECTION",
        severity="YELLOW",
        confidence=0.75,
        details={"pattern": "jailbreak"},
        reviewed=False,
    ),
]

assert len(FLAG_SPECS) == 10
assert sum(1 for f in FLAG_SPECS if f.reviewed) == 6
assert sum(1 for f in FLAG_SPECS if not f.reviewed) == 4


async def _create_flags(
    db: AsyncSession, logs: list[AuditLog], rng: random.Random
) -> list[SafetyFlag]:
    # Bias flag attachment toward high/critical-risk active models so the
    # review queue feels relevant. Pull model_version straight from the DB
    # to avoid triggering an async lazy-load on log.model.
    high_risk_versions = {
        m.model_version for m in MODELS if m.risk_level in ("High", "Critical")
    }
    rows = (await db.execute(select(ModelRegistry.id, ModelRegistry.model_version))).all()
    version_by_id = {row[0]: row[1] for row in rows}
    candidates = [
        log for log in logs
        if version_by_id.get(log.model_id) in high_risk_versions
        and log.status == "success"
    ]
    if len(candidates) < len(FLAG_SPECS):
        candidates = [log for log in logs if log.status == "success"]

    chosen_logs = rng.sample(candidates, k=len(FLAG_SPECS))
    flags: list[SafetyFlag] = []
    for spec, log in zip(FLAG_SPECS, chosen_logs):
        # Promote the log to flagged with matching severity.
        log.flagged = True
        log.flag_severity = spec.severity

        flag = SafetyFlag(
            log_id=log.id,
            model_id=log.model_id,
            # Place the flag slightly after the log so the timeline reads naturally.
            timestamp=log.timestamp + timedelta(seconds=rng.randint(1, 90)),
            flag_type=spec.flag_type,
            severity=spec.severity,
            confidence=spec.confidence,
            details=spec.details,
            reviewed=spec.reviewed,
            reviewed_by=ADMIN_EMAIL if spec.reviewed else None,
            reviewed_at=(
                log.timestamp + timedelta(hours=rng.randint(1, 24))
                if spec.reviewed else None
            ),
            review_status=spec.review_status,
            review_notes=spec.review_notes,
        )
        db.add(flag)
        flags.append(flag)
    await db.flush()
    return flags


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------


async def main(reset: bool) -> None:
    async with AsyncSessionLocal() as db:
        if await _demo_rows_exist(db):
            if not reset:
                print(
                    "Demo data already present. Re-run with --reset to wipe and reseed.",
                    file=sys.stderr,
                )
                sys.exit(1)
            await _wipe_demo(db)

        rng = random.Random(SEED)

        await _upsert_pricing(db)
        admin, viewer = await _create_users(db)
        models = await _create_models(db)
        logs = await _create_logs(db, models, rng)
        flags = await _create_flags(db, logs, rng)

        await db.commit()

        print(
            f"Seeded: 2 users, {len(models)} models, {len(logs)} logs, "
            f"{len(flags)} flags. Login: {ADMIN_EMAIL}"
        )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--reset",
        action="store_true",
        help="Wipe demo rows (only those tied to the demo accounts) before seeding.",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(reset=args.reset))
