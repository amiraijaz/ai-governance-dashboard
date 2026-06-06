"""Safety checks: PII (Presidio), toxicity (OpenAI Moderation), prompt injection (regex)."""

import asyncio
import sys
import threading
from typing import Any, Optional

import httpx

from config import settings

INJECTION_PATTERNS: list[str] = [
    "ignore previous instructions",
    "ignore all previous",
    "disregard your instructions",
    "you are now",
    "act as if",
    "pretend you are",
    "jailbreak",
    "dan mode",
    "bypass your",
    "override your instructions",
]

_GREEN, _YELLOW, _RED = "GREEN", "YELLOW", "RED"


class SafetyChecker:
    """Lazy Presidio + spaCy.

    The spaCy model is several hundred MB resident. On Render's 512 MB free
    plan we cannot afford to load it at boot — most requests never trigger
    a safety check, and the ones that do run as background tasks where a
    cold first load is acceptable. The model loads on the first PII flag
    and is reused for the life of the process.

    The init path is guarded by a `threading.Lock` because `_pii_flag`
    dispatches through `asyncio.to_thread`, so concurrent first calls
    would otherwise race to instantiate the engine twice.
    """

    def __init__(self) -> None:
        self._analyzer: Any | None = None
        self._presidio_unavailable: bool = False
        self._lock = threading.Lock()

    def _ensure_analyzer(self) -> Any | None:
        # Fast path: already loaded (or known unavailable).
        if self._analyzer is not None or self._presidio_unavailable:
            return self._analyzer
        with self._lock:
            # Re-check inside the lock — another thread may have raced ahead.
            if self._analyzer is not None or self._presidio_unavailable:
                return self._analyzer
            try:
                from presidio_analyzer import AnalyzerEngine
                from presidio_analyzer.nlp_engine import NlpEngineProvider

                provider = NlpEngineProvider(
                    nlp_configuration={
                        "nlp_engine_name": "spacy",
                        "models": [{"lang_code": "en", "model_name": settings.SPACY_MODEL}],
                    }
                )
                self._analyzer = AnalyzerEngine(nlp_engine=provider.create_engine())
            except Exception as exc:
                print(f"[safety] Presidio unavailable: {exc}", file=sys.stderr)
                self._presidio_unavailable = True
        return self._analyzer

    async def _pii_flag(self, text: str) -> Optional[dict[str, Any]]:
        analyzer = await asyncio.to_thread(self._ensure_analyzer)
        if analyzer is None:
            return None

        results = await asyncio.to_thread(analyzer.analyze, text, "en")
        if not results:
            return None
        return {
            "type": "PII_DETECTED",
            "details": sorted({r.entity_type for r in results}),
            "confidence": float(max(r.score for r in results)),
        }

    async def _toxicity_flag(self, text: str) -> Optional[dict[str, Any]]:
        if not settings.OPENAI_API_KEY:
            return None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/moderations",
                    headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                    json={"input": text},
                )
                resp.raise_for_status()
                mod = resp.json()["results"][0]
        except Exception as exc:
            print(f"[safety] moderation API failed: {exc}", file=sys.stderr)
            return None

        if not mod.get("flagged"):
            return None
        categories = mod.get("categories", {})
        scores = mod.get("category_scores", {})
        return {
            "type": "TOXICITY",
            "details": {k: v for k, v in categories.items() if v},
            "confidence": float(max(scores.values()) if scores else 0.9),
        }

    def _injection_flag(self, text: str) -> Optional[dict[str, Any]]:
        lowered = text.lower()
        for pattern in INJECTION_PATTERNS:
            if pattern in lowered:
                return {
                    "type": "PROMPT_INJECTION",
                    "details": f"Pattern: '{pattern}'",
                    "confidence": 0.85,
                }
        return None

    async def check(self, text: str) -> dict[str, Any]:
        pii, toxicity = await asyncio.gather(
            self._pii_flag(text),
            self._toxicity_flag(text),
        )
        flags = [f for f in (pii, toxicity, self._injection_flag(text)) if f is not None]

        if not flags:
            return {"flagged": False, "severity": _GREEN, "flags": []}

        max_conf = max(f["confidence"] for f in flags)
        severity = _RED if max_conf >= 0.8 else _YELLOW
        return {"flagged": True, "severity": severity, "flags": flags}


safety_checker = SafetyChecker()
