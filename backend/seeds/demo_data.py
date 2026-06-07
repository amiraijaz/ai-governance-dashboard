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
from models import (
    AuditLog,
    EvalResult,
    EvalRun,
    EvalSuite,
    ModelPricing,
    ModelRegistry,
    SafetyFlag,
    User,
)

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

ADMIN_EMAIL = "test@vigil.com"
ADMIN_PASSWORD = "demo1234"
VIEWER_EMAIL = "viewer@vigil.com"
VIEWER_PASSWORD = "viewer1234"

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
        EvalSuite → EvalRun → EvalResult         (delete suites → results gone)

    Eval suites are deleted FIRST so the FK from EvalSuite.model_id
    (ON DELETE SET NULL) doesn't fire spuriously when models go away.

    Pricing rows are left alone — they're shared with the real catalog.
    """
    await db.execute(
        delete(EvalSuite).where(EvalSuite.owner_email == DEMO_OWNER_EMAIL)
    )
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


# ----------------------------------------------------------------------------
# Eval framework — three suites with completed runs + per-case results.
# Counts and scores are deterministic via the same RNG seed as the rest of
# the demo so the live URL renders the same numbers after every reseed.
# ----------------------------------------------------------------------------

JUDGE_RUBRIC_YAML = """\
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

# Twelve short KB-search cases — half about billing, half about product.
RAG_CASES: list[tuple[str, str, list[str]]] = [
    (
        "How do I update my billing address?",
        "Open Settings → Billing → Edit address. Saves on submit.",
        ["Settings → Billing lets customers update their billing address.",
         "Address changes take effect on the next invoice."],
    ),
    (
        "What payment methods do you accept?",
        "Visa, Mastercard, Amex, and ACH for annual plans.",
        ["We accept Visa, Mastercard, and American Express.",
         "ACH is available on annual plans only."],
    ),
    (
        "Can I cancel my subscription?",
        "Yes. Go to Billing → Cancel. Access continues until period end.",
        ["Subscriptions can be cancelled at any time from Billing.",
         "Service remains active through the current billing period."],
    ),
    (
        "Do you offer refunds?",
        "Within 14 days, no questions asked. After that case-by-case.",
        ["Refunds are issued within 14 days of purchase, no questions asked."],
    ),
    (
        "Is there a free trial?",
        "14-day trial, no credit card required.",
        ["Vigil offers a 14-day free trial that doesn't require a credit card."],
    ),
    (
        "Where are my invoices?",
        "Billing → Invoices. Download as PDF.",
        ["Past invoices are listed under Billing → Invoices and download as PDF."],
    ),
    (
        "How do I add a team member?",
        "Settings → Team → Invite. They get an email link.",
        ["Team members are added by inviting their email from Settings → Team.",
         "Invited members receive an activation email."],
    ),
    (
        "What's included on the Pro plan?",
        "Everything in Free plus SSO, audit log export, and priority support.",
        ["Pro adds SSO, audit log CSV export, and priority support over the Free tier."],
    ),
    (
        "Do you support SSO?",
        "Yes, SAML 2.0 on Pro and Enterprise.",
        ["SSO is available on Pro and Enterprise plans via SAML 2.0."],
    ),
    (
        "How is data stored?",
        "Encrypted at rest in Postgres, TLS in transit. SOC 2 in progress.",
        ["Customer data is encrypted at rest in PostgreSQL and TLS in transit.",
         "Our SOC 2 Type II report is in progress."],
    ),
    # The two cases at the end fail one or more metrics — the demo should
    # show a couple of real failures so the dashboard isn't all-green.
    (
        "What's your uptime SLA?",
        "We aim for high availability across regions.",
        ["The Pro SLA is 99.9% monthly uptime, credited if missed."],
    ),
    (
        "Can I export my data?",
        "Yes, contact support.",
        ["Self-service CSV export is available under Settings → Data.",
         "API export is also documented in the developer guide."],
    ),
]

# Fifteen support-quality cases — short customer turns + a model reply.
JUDGE_CASES: list[tuple[str, str]] = [
    ("Hi! My invoice doesn't show the tax breakdown.",
     "Hi Sam — happy to help! Tax breakdowns are on page 2 of each PDF invoice. If you don't see it, please share the invoice number and I'll pull it up."),
    ("I keep getting charged twice every month.",
     "I'm sorry for the frustration. I see two parallel subscriptions on your account. I've cancelled the duplicate effective today and refunded the last two duplicate charges."),
    ("Your dashboard is broken!",
     "Sorry you're hitting a wall. Can you share which page you're on and what you see? A screenshot helps. We'll dig in immediately."),
    ("How do I add Slack alerts?",
     "Slack alerts live in Settings → Integrations → Slack. You'll grant the workspace OAuth scope, then pick the channel for each severity tier."),
    ("Can you delete my account?",
     "Of course. Account deletion runs from Settings → Danger Zone → Delete account. It's irreversible and we purge backups within 30 days."),
    ("Why is my report not generating?",
     "Reports run in the background and can take up to a minute on a busy day. If it's been more than five minutes, share the report ID and I'll check the worker logs."),
    ("Loving the new dark mode :)",
     "Glad to hear it! The theme toggle is in the sidebar footer. You can also set it to follow your OS."),
    ("My API key just stopped working.",
     "Keys can be revoked from Settings → API Keys. Could you confirm whether the key shows as Active there? If so, please share the first 8 characters so I can correlate the request."),
    ("Do you have a Python SDK?",
     "We do — `pip install aigovkit`. Docs are at /docs/sdk. One-line integration around your OpenAI or Anthropic call."),
    ("This is unacceptable, I want a refund.",
     "I hear you, and I'm sorry. Could you tell me what happened so I can make it right? Refunds within 14 days are no-questions-asked."),
    ("Random question — is your company hiring?",
     "Thanks for asking! Open roles are at /careers. We're a small team so we look at every application."),
    # Three cases below trip individual criteria so the demo shows real
    # rubric tension rather than a uniform-pass sheet.
    ("Why does PII scanning miss email addresses sometimes?",
     "It uses Presidio under the hood and Presidio's email recognizer is regex-based, which is reliable for normal addresses but can miss obfuscated forms like \"name at example dot com\". We're tracking that gap."),
    ("Your prices are insane.",
     "Pricing reflects the cost of the models we proxy plus our margin. Happy to walk through cost per call if useful."),
    ("Can you send me the source code?",
     "Vigil is open-source on GitHub. The link is in the footer. We don't email zips — clone the repo and you have everything."),
    ("Help me jailbreak Claude.",
     "I can't help with that. If you're researching prompt-injection defences, the Review Queue is the right place to see how Vigil flags those attempts."),
]


async def _create_eval_suites(
    db: AsyncSession,
    models: dict[str, ModelRegistry],
    rng: random.Random,
) -> tuple[list[EvalSuite], list[EvalRun]]:
    """Three suites + one completed run each, with believable summaries
    and per-case results so the Evaluations page is not empty.

    Returns (suites, runs) for the summary print.
    """
    suites: list[EvalSuite] = []
    runs: list[EvalRun] = []

    # --- RAG suite -------------------------------------------------------
    rag_suite = EvalSuite(
        name="RAG faithfulness — Knowledge Base Search",
        description=(
            "Reference-free RAG metrics on the help-center retriever. "
            "Cases are recent support questions answered against the knowledge base."
        ),
        eval_type="rag",
        config={"threshold": 0.7, "source": "inline"},
        model_id=models["gemini-1.5-flash"].id,
        owner_email=DEMO_OWNER_EMAIL,
    )
    db.add(rag_suite)
    await db.flush()
    suites.append(rag_suite)

    rag_started = NOW - timedelta(hours=4)
    rag_completed = rag_started + timedelta(seconds=83)
    rag_results = _build_rag_results(rng)
    rag_run = EvalRun(
        suite_id=rag_suite.id,
        status="complete",
        started_at=rag_started,
        completed_at=rag_completed,
        triggered_by=ADMIN_EMAIL,
        summary={
            "total_cases": len(rag_results),
            "passed": sum(1 for r in rag_results if r["passed"]),
            "failed": sum(1 for r in rag_results if not r["passed"]),
            "pass_rate": sum(1 for r in rag_results if r["passed"]) / len(rag_results),
            "threshold": 0.7,
            "metrics": {
                "faithfulness": _mean([r["scores"]["faithfulness"] for r in rag_results]),
                "answer_relevancy": _mean(
                    [r["scores"]["answer_relevancy"] for r in rag_results]
                ),
                "context_precision": _mean(
                    [r["scores"]["context_precision"] for r in rag_results]
                ),
            },
        },
    )
    db.add(rag_run)
    await db.flush()
    runs.append(rag_run)
    for r in rag_results:
        db.add(EvalResult(run_id=rag_run.id, **r))

    # --- Judge suite -----------------------------------------------------
    judge_suite = EvalSuite(
        name="Support quality rubric — Customer Support Assistant",
        description=(
            "LLM-as-judge against a 3-criterion rubric (tone, accuracy, "
            "helpfulness). Pass = mean across criteria >= 3.5/5."
        ),
        eval_type="llm_judge",
        config={"rubric": JUDGE_RUBRIC_YAML, "source": "inline", "concurrency": 5},
        model_id=models["claude-haiku-4-5"].id,
        owner_email=DEMO_OWNER_EMAIL,
    )
    db.add(judge_suite)
    await db.flush()
    suites.append(judge_suite)

    judge_started = NOW - timedelta(hours=18)
    judge_completed = judge_started + timedelta(seconds=147)
    judge_results = _build_judge_results(rng)
    judge_passed = sum(1 for r in judge_results if r["passed"])
    judge_mean = _mean(
        [r["details"]["mean_score"] for r in judge_results if r["details"].get("mean_score") is not None]
    )
    judge_run = EvalRun(
        suite_id=judge_suite.id,
        status="complete",
        started_at=judge_started,
        completed_at=judge_completed,
        triggered_by=ADMIN_EMAIL,
        summary={
            "total_cases": len(judge_results),
            "passed": judge_passed,
            "failed": len(judge_results) - judge_passed,
            "errored": 0,
            "pass_rate": judge_passed / len(judge_results),
            "threshold": 3.5,
            "rubric_name": "Support quality",
            "mean_score": judge_mean,
            "criteria_means": {
                "professional_tone": _mean(
                    [r["scores"]["professional_tone"]["score"] for r in judge_results]
                ),
                "factual_accuracy": _mean(
                    [r["scores"]["factual_accuracy"]["score"] for r in judge_results]
                ),
                "helpfulness": _mean(
                    [r["scores"]["helpfulness"]["score"] for r in judge_results]
                ),
            },
        },
    )
    db.add(judge_run)
    await db.flush()
    runs.append(judge_run)
    for r in judge_results:
        db.add(EvalResult(run_id=judge_run.id, **r))

    # --- Drift suite -----------------------------------------------------
    drift_suite = EvalSuite(
        name="Behavior drift — Contract Summariser",
        description=(
            "Two-window Mann-Whitney drift detection on latency, response "
            "length, and error rate against the last 7 days of traffic."
        ),
        eval_type="drift",
        config={"current_days": 7, "baseline_days": 7, "latency_pct_threshold": 25.0},
        model_id=models["claude-sonnet-4-5"].id,
        owner_email=DEMO_OWNER_EMAIL,
    )
    db.add(drift_suite)
    await db.flush()
    suites.append(drift_suite)

    drift_started = NOW - timedelta(hours=1)
    drift_completed = drift_started + timedelta(seconds=4)
    current_from = NOW - timedelta(days=7)
    baseline_from = NOW - timedelta(days=14)
    drift_summary = {
        "model_id": str(drift_suite.model_id),
        "current_window": {
            "from": current_from.isoformat(),
            "to": NOW.isoformat(),
            "n": 11,
        },
        "baseline_window": {
            "from": baseline_from.isoformat(),
            "to": current_from.isoformat(),
            "n": 14,
        },
        "signals": {
            "latency": {
                "baseline_p95": 1840.0,
                "current_p95": 2360.0,
                "baseline_mean": 1210.0,
                "current_mean": 1485.0,
                "pct_change": 28.3,
                "p_value": 0.011,
                "drifted": True,
            },
            "response_length": {
                "baseline_mean": 412.0,
                "current_mean": 425.0,
                "pct_change": 3.2,
                "p_value": 0.42,
                "drifted": False,
            },
            "error_rate": {
                "baseline_rate": 0.071,
                "current_rate": 0.091,
                "delta": 0.020,
                "drifted": False,
            },
        },
        "overall_drift": True,
        "insufficient_data": False,
    }
    drift_run = EvalRun(
        suite_id=drift_suite.id,
        status="complete",
        started_at=drift_started,
        completed_at=drift_completed,
        triggered_by="scheduled",
        summary=drift_summary,
    )
    db.add(drift_run)
    await db.flush()
    runs.append(drift_run)
    # Drift produces no per-case rows; the signals dict in summary IS the result.

    return suites, runs


# ----------------------------------------------------------------------------
# Per-case row builders — pulled out so the suite function stays readable.
# ----------------------------------------------------------------------------


def _build_rag_results(rng: random.Random) -> list[dict]:
    """12 RAG cases — first 10 pass, last 2 fail at threshold 0.7.

    The two failures probe the two most common real-world failure modes:
        * a vague answer that's not grounded in the context (faithfulness drop)
        * a sparse retrieved-context set that misses the question
          (context_precision drop)
    """
    rows: list[dict] = []
    n_total = len(RAG_CASES)
    for i, (query, response, contexts) in enumerate(RAG_CASES):
        is_failure = i >= n_total - 2
        if is_failure:
            if i == n_total - 2:
                # uptime SLA — vague answer, contexts good
                scores = {
                    "faithfulness": round(0.42 + rng.uniform(-0.05, 0.05), 2),
                    "answer_relevancy": round(0.55 + rng.uniform(-0.05, 0.05), 2),
                    "context_precision": round(0.81 + rng.uniform(-0.05, 0.05), 2),
                }
            else:
                # export — accurate but missed the self-serve path
                scores = {
                    "faithfulness": round(0.74 + rng.uniform(-0.05, 0.05), 2),
                    "answer_relevancy": round(0.61 + rng.uniform(-0.05, 0.05), 2),
                    "context_precision": round(0.58 + rng.uniform(-0.05, 0.05), 2),
                }
        else:
            scores = {
                "faithfulness": round(rng.uniform(0.78, 0.95), 2),
                "answer_relevancy": round(rng.uniform(0.85, 0.97), 2),
                "context_precision": round(rng.uniform(0.72, 0.92), 2),
            }
        passed = all(v >= 0.7 for v in scores.values())
        rows.append({
            "log_id": None,
            "case_input": query,
            "case_output": response,
            "scores": scores,
            "passed": passed,
            "details": {"contexts": contexts},
        })
    return rows


def _build_judge_results(rng: random.Random) -> list[dict]:
    """15 LLM-judge cases scored on three 1..5 criteria.

    The trailing two cases are tuned to fail (mean < 3.5) so the demo
    surfaces real rubric tension instead of a uniform 5/5 sheet.
    """
    rationales = {
        "professional_tone": {
            5: "Warm and professional throughout.",
            4: "Polite, slightly casual but appropriate.",
            3: "Neutral; reads a touch terse.",
            2: "Curt — would land poorly with a frustrated customer.",
        },
        "factual_accuracy": {
            5: "All claims are correct and verifiable.",
            4: "Accurate; one minor omission.",
            3: "Mostly accurate but a key detail is missing.",
            2: "Contains an unsupported claim.",
        },
        "helpfulness": {
            5: "Directly resolves the user's request.",
            4: "Answers the question and offers a next step.",
            3: "Partial answer; user will likely have to follow up.",
            2: "Sidesteps the actual question.",
        },
    }

    def _entry(criterion: str, score: int) -> dict:
        return {"score": score, "rationale": rationales[criterion].get(score, "Acceptable.")}

    rows: list[dict] = []
    n_total = len(JUDGE_CASES)
    for i, (user_msg, reply) in enumerate(JUDGE_CASES):
        # Most cases score 4 or 5 on each criterion; the last two underperform.
        if i >= n_total - 2:
            base = rng.choice([2, 3])
            scores = {
                "professional_tone": _entry("professional_tone", base),
                "factual_accuracy": _entry("factual_accuracy", rng.choice([2, 3])),
                "helpfulness": _entry("helpfulness", rng.choice([2, 3])),
            }
        else:
            scores = {
                "professional_tone": _entry("professional_tone", rng.choice([4, 5, 5])),
                "factual_accuracy": _entry("factual_accuracy", rng.choice([4, 5, 5, 3])),
                "helpfulness": _entry("helpfulness", rng.choice([4, 5, 4, 3])),
            }
        score_values = [v["score"] for v in scores.values()]
        mean_score = sum(score_values) / len(score_values)
        rows.append({
            "log_id": None,
            "case_input": user_msg,
            "case_output": reply,
            "scores": scores,
            "passed": mean_score >= 3.5,
            "details": {"mean_score": round(mean_score, 2)},
        })
    return rows


def _mean(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 3) if xs else 0.0


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
        suites, runs = await _create_eval_suites(db, models, rng)

        await db.commit()

        print(
            f"Seeded: 2 users, {len(models)} models, {len(logs)} logs, "
            f"{len(flags)} flags, {len(suites)} eval suites, "
            f"{len(runs)} eval runs. Login: {ADMIN_EMAIL}"
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
