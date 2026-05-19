import asyncio
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AuditLog, ModelRegistry, SafetyFlag

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _to_dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


class ReportGenerator:
    async def _executive_summary(
        self,
        db: AsyncSession,
        start: datetime,
        end: datetime,
        model_filter,
    ) -> dict[str, Any]:
        models_registered = await db.scalar(
            select(func.count(ModelRegistry.id)).where(*model_filter)
        ) or 0
        total_calls = await db.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.timestamp >= start, AuditLog.timestamp < end
            )
        ) or 0
        total_cost = await db.scalar(
            select(func.coalesce(func.sum(AuditLog.total_cost_usd), 0.0)).where(
                AuditLog.timestamp >= start, AuditLog.timestamp < end
            )
        ) or 0.0
        open_flags = await db.scalar(
            select(func.count(SafetyFlag.id)).where(
                SafetyFlag.reviewed.is_(False),
                SafetyFlag.timestamp >= start,
                SafetyFlag.timestamp < end,
            )
        ) or 0
        return {
            "models_registered": int(models_registered),
            "total_calls": int(total_calls),
            "total_cost": float(total_cost),
            "open_flags": int(open_flags),
        }

    async def _models(
        self, db: AsyncSession, model_filter
    ) -> list[ModelRegistry]:
        result = await db.execute(
            select(ModelRegistry)
            .where(*model_filter)
            .order_by(ModelRegistry.risk_level.desc(), ModelRegistry.name)
        )
        return list(result.scalars().all())

    async def _audit_section(
        self,
        db: AsyncSession,
        start: datetime,
        end: datetime,
    ) -> dict[str, Any]:
        total_calls = await db.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.timestamp >= start, AuditLog.timestamp < end
            )
        ) or 0
        flagged_calls = await db.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.timestamp >= start,
                AuditLog.timestamp < end,
                AuditLog.flagged.is_(True),
            )
        ) or 0
        total_cost = await db.scalar(
            select(func.coalesce(func.sum(AuditLog.total_cost_usd), 0.0)).where(
                AuditLog.timestamp >= start, AuditLog.timestamp < end
            )
        ) or 0.0

        rows = (
            await db.execute(
                select(
                    ModelRegistry.name,
                    func.count(AuditLog.id).label("calls"),
                    func.coalesce(func.sum(AuditLog.total_cost_usd), 0.0).label("cost"),
                )
                .join(AuditLog, AuditLog.model_id == ModelRegistry.id)
                .where(AuditLog.timestamp >= start, AuditLog.timestamp < end)
                .group_by(ModelRegistry.name)
                .order_by(func.sum(AuditLog.total_cost_usd).desc().nullslast())
            )
        ).all()

        return {
            "total_calls": int(total_calls),
            "flagged_calls": int(flagged_calls),
            "flagged_pct": (100.0 * flagged_calls / total_calls) if total_calls else 0.0,
            "total_cost": float(total_cost),
            "by_model": [
                {"name": r.name, "calls": int(r.calls), "cost": float(r.cost)}
                for r in rows
            ],
        }

    async def _safety_section(
        self,
        db: AsyncSession,
        start: datetime,
        end: datetime,
    ) -> dict[str, Any]:
        row = (
            await db.execute(
                select(
                    func.sum(case((SafetyFlag.severity == "GREEN", 1), else_=0)).label("green"),
                    func.sum(case((SafetyFlag.severity == "YELLOW", 1), else_=0)).label("yellow"),
                    func.sum(case((SafetyFlag.severity == "RED", 1), else_=0)).label("red"),
                    func.sum(case((SafetyFlag.reviewed.is_(True), 1), else_=0)).label("reviewed"),
                ).where(SafetyFlag.timestamp >= start, SafetyFlag.timestamp < end)
            )
        ).one()

        top_rows = (
            await db.execute(
                select(SafetyFlag.flag_type, func.count(SafetyFlag.id).label("count"))
                .where(SafetyFlag.timestamp >= start, SafetyFlag.timestamp < end)
                .group_by(SafetyFlag.flag_type)
                .order_by(func.count(SafetyFlag.id).desc())
                .limit(5)
            )
        ).all()

        return {
            "green": int(row.green or 0),
            "yellow": int(row.yellow or 0),
            "red": int(row.red or 0),
            "reviewed": int(row.reviewed or 0),
            "top_types": [
                {"flag_type": r.flag_type, "count": int(r.count)} for r in top_rows
            ],
        }

    async def _open_issues(
        self,
        db: AsyncSession,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        rows = (
            await db.execute(
                select(
                    SafetyFlag,
                    ModelRegistry.name.label("model_name"),
                )
                .join(ModelRegistry, ModelRegistry.id == SafetyFlag.model_id, isouter=True)
                .where(
                    SafetyFlag.reviewed.is_(False),
                    SafetyFlag.severity.in_(["RED", "YELLOW"]),
                    SafetyFlag.timestamp >= start,
                    SafetyFlag.timestamp < end,
                )
                .order_by(
                    case((SafetyFlag.severity == "RED", 0), else_=1),
                    SafetyFlag.timestamp.desc(),
                )
                .limit(50)
            )
        ).all()
        return [
            {
                "timestamp": flag.timestamp.strftime("%Y-%m-%d %H:%M"),
                "model_name": model_name,
                "flag_type": flag.flag_type,
                "severity": flag.severity,
                "confidence": float(flag.confidence),
            }
            for flag, model_name in rows
        ]

    async def _render_html(
        self,
        date_from: date,
        date_to: date,
        organisation: Optional[str],
        summary: dict,
        models: list[ModelRegistry],
        audit: dict,
        safety: dict,
        open_issues: list[dict],
    ) -> str:
        template = _env.get_template("report.html")
        return template.render(
            organisation=organisation,
            date_from=date_from.isoformat(),
            date_to=date_to.isoformat(),
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            summary=summary,
            models=models,
            audit=audit,
            safety=safety,
            open_issues=open_issues,
        )

    async def generate(
        self,
        db: AsyncSession,
        date_from: date,
        date_to: date,
        model_ids: Optional[list[str]] = None,
        organisation: Optional[str] = None,
    ) -> bytes:
        # Inclusive of date_to: query through end-of-day.
        start = _to_dt(date_from)
        end = _to_dt(date_to).replace(hour=23, minute=59, second=59)

        model_filter = []
        if model_ids:
            model_filter.append(ModelRegistry.id.in_(model_ids))

        summary = await self._executive_summary(db, start, end, model_filter)
        models = await self._models(db, model_filter)
        audit = await self._audit_section(db, start, end)
        safety = await self._safety_section(db, start, end)
        open_issues = await self._open_issues(db, start, end)

        html = await self._render_html(
            date_from, date_to, organisation, summary, models, audit, safety, open_issues
        )

        # WeasyPrint is sync; offload to a thread to keep the event loop free.
        def _to_pdf(source: str) -> bytes:
            from weasyprint import HTML

            return HTML(string=source).write_pdf()

        pdf_bytes = await asyncio.to_thread(_to_pdf, html)
        return pdf_bytes


report_generator = ReportGenerator()
