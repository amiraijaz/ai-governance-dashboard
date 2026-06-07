import hashlib
import time
from typing import Any, Optional

import httpx


class AIGovLogger:
    """Synchronous one-line wrapper around LLM calls.

    Logs every call to an AI Governance Dashboard instance. Network and
    provider errors during logging are swallowed so logging never breaks
    the host application.
    """

    def __init__(
        self,
        api_key: str,
        model_id: str,
        dashboard_url: str = "http://localhost:8000",
        log_raw_prompts: bool = False,
        log_responses: bool = False,
        token: Optional[str] = None,
    ):
        self.api_key = api_key
        self.model_id = model_id
        self.dashboard_url = dashboard_url.rstrip("/")
        self.log_raw_prompts = log_raw_prompts
        self.log_responses = log_responses
        # Session JWT for dashboard-backed evals (different from api_key,
        # which is the X-API-Key used by /api/logs ingest). Lazily-built
        # client lives behind the .evals property.
        self._eval_token = token
        self._evals: Optional["DashboardEvals"] = None  # type: ignore[name-defined]

    @property
    def evals(self) -> "DashboardEvals":  # type: ignore[name-defined]
        """Dashboard-backed evals client (Mode B).

        See ``vigilai.evals`` for the local-mode entry points (``judge``,
        ``rag``, ``drift``). This property returns a thin sync client that
        talks to /api/evals on ``self.dashboard_url`` using the session
        JWT supplied via ``token=`` on construction (or ``VIGILAI_TOKEN``
        in the environment).
        """
        if self._evals is None:
            from .evals import DashboardEvals  # local import keeps import-time cheap
            self._evals = DashboardEvals(
                dashboard_url=self.dashboard_url,
                token=self._eval_token,
            )
        return self._evals

    @staticmethod
    def _hash_prompt(messages: list[dict]) -> str:
        return hashlib.sha256(str(messages).encode("utf-8")).hexdigest()

    def call(
        self,
        provider: str,
        model: str,
        messages: list[dict],
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        max_tokens: int = 1024,
        **kwargs: Any,
    ):
        start = time.perf_counter()
        status = "success"
        prompt_tokens = 0
        completion_tokens = 0
        response: Any = None
        response_text: Optional[str] = None

        try:
            if provider == "anthropic":
                import anthropic

                client = anthropic.Anthropic()
                response = client.messages.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    **kwargs,
                )
                prompt_tokens = response.usage.input_tokens
                completion_tokens = response.usage.output_tokens
                try:
                    response_text = response.content[0].text
                except Exception:
                    response_text = None

            elif provider == "openai":
                import openai

                client = openai.OpenAI()
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    **kwargs,
                )
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens
                try:
                    response_text = response.choices[0].message.content
                except Exception:
                    response_text = None

            else:
                raise ValueError(f"Unsupported provider: {provider}")

        except Exception:
            status = "error"
            raise
        finally:
            latency_ms = int((time.perf_counter() - start) * 1000)
            payload: dict[str, Any] = {
                "model_id": self.model_id,
                "prompt_hash": self._hash_prompt(messages),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "latency_ms": latency_ms,
                "user_id": user_id,
                "session_id": session_id,
                "status": status,
            }
            if self.log_raw_prompts:
                payload["metadata"] = {"messages": messages}
            if self.log_responses and response_text is not None:
                payload["response_text"] = response_text
            self._send_log(payload)

        return response

    def _send_log(self, payload: dict) -> None:
        try:
            httpx.post(
                f"{self.dashboard_url}/api/logs/",
                json=payload,
                headers={"X-API-Key": self.api_key},
                timeout=2.0,
            )
        except Exception:
            pass
