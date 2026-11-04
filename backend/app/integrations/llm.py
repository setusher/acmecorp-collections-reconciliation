"""Provider-agnostic LLM wrapper.

Configured by env vars: LLM_PROVIDER (gemini | groq | openai_compatible | none),
LLM_API_KEY, LLM_MODEL, LLM_FALLBACK_MODEL, LLM_BASE_URL, LLM_TIMEOUT_SECONDS.
Only one method is needed by the app: ``complete_json(system, user) -> dict``.
Any failure raises :class:`LLMError`; callers route the message to a human.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Protocol

import httpx

from app.core.config import Settings

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """LLM unavailable, timed out, or returned unusable output."""


class LLMClient(Protocol):
    name: str

    async def complete_json(self, system: str, user: str) -> dict: ...


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise LLMError("LLM did not return JSON")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError("LLM returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise LLMError("LLM JSON is not an object")
    return data


class _HTTPClient:
    name = "base"

    def __init__(self, api_key: str, models: list[str], timeout: float,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.api_key = api_key
        self.models = [m for m in models if m]
        self.timeout = timeout
        self.transport = transport  # injectable for tests

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout, transport=self.transport)

    async def _call(self, model: str, system: str, user: str) -> str:  # pragma: no cover - network
        raise NotImplementedError

    async def complete_json(self, system: str, user: str) -> dict:
        if not self.api_key or not self.models:
            raise LLMError(f"{self.name}: API key or model not configured")
        last: Exception | None = None
        for model in self.models:
            try:
                return _extract_json(await self._call(model, system, user))
            except (httpx.HTTPError, LLMError, KeyError, IndexError, TypeError) as exc:
                # Never log the key or the prompt; status + model is enough to debug.
                status = getattr(getattr(exc, "response", None), "status_code", None)
                log.warning("LLM call failed provider=%s model=%s status=%s err=%s", self.name, model, status,
                            type(exc).__name__)
                last = exc
        raise LLMError(f"{self.name}: all models failed ({type(last).__name__})")


class GeminiClient(_HTTPClient):
    name = "gemini"
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    async def _call(self, model: str, system: str, user: str) -> str:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        }
        async with self._client() as client:
            r = await client.post(self.URL.format(model=model), json=body, headers={"x-goog-api-key": self.api_key})
            r.raise_for_status()
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]


class OpenAICompatibleClient(_HTTPClient):
    name = "openai_compatible"

    def __init__(self, api_key: str, models: list[str], timeout: float, base_url: str,
                 transport: httpx.AsyncBaseTransport | None = None):
        super().__init__(api_key, models, timeout, transport)
        self.base_url = base_url.rstrip("/")

    async def _call(self, model: str, system: str, user: str) -> str:
        body = {
            "model": model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        async with self._client() as client:
            r = await client.post(f"{self.base_url}/chat/completions", json=body,
                                  headers={"Authorization": f"Bearer {self.api_key}"})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]


class DisabledClient:
    name = "none"

    async def complete_json(self, system: str, user: str) -> dict:
        raise LLMError("LLM is disabled (LLM_PROVIDER=none)")


class FakeLLM:
    """Deterministic stand-in used by tests and offline demos. Returns queued responses in order."""

    name = "fake"

    def __init__(self, responses: list[dict | Exception] | None = None):
        self.responses = list(responses or [])
        self.calls: list[tuple[str, str]] = []

    async def complete_json(self, system: str, user: str) -> dict:
        self.calls.append((system, user))
        if not self.responses:
            raise LLMError("fake LLM has no queued response")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def build_llm(settings: Settings) -> LLMClient:
    provider = (settings.llm_provider or "none").lower()
    models = [settings.llm_model, settings.llm_fallback_model]
    if provider == "gemini":
        return GeminiClient(settings.llm_api_key, models, settings.llm_timeout_seconds)
    if provider == "groq":
        return OpenAICompatibleClient(settings.llm_api_key, models, settings.llm_timeout_seconds,
                                      settings.llm_base_url or "https://api.groq.com/openai/v1")
    if provider in ("openai_compatible", "openai"):
        return OpenAICompatibleClient(settings.llm_api_key, models, settings.llm_timeout_seconds,
                                      settings.llm_base_url or "https://api.openai.com/v1")
    return DisabledClient()
