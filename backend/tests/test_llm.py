import json

import httpx
import pytest

from app.core.config import Settings
from app.integrations.llm import DisabledClient, GeminiClient, LLMError, OpenAICompatibleClient, build_llm

PAYLOAD = {"category": "payment_info_query", "confidence": 0.9, "needs_attention": False, "reason": "r",
           "draft_reply": "Hi {{FACTS}}"}


async def test_gemini_request_and_parse():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["key"], seen["body"] = str(req.url), req.headers.get("x-goog-api-key"), json.loads(req.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(PAYLOAD)}]}}]})

    c = GeminiClient("k123", ["gem-a"], 5, transport=httpx.MockTransport(handler))
    assert await c.complete_json("sys", "usr") == PAYLOAD
    assert "models/gem-a:generateContent" in seen["url"] and "k123" not in seen["url"]  # key in header, not URL
    assert seen["key"] == "k123"
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "sys"
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"


async def test_fallback_model_used_on_error():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if "primary" in str(req.url):
            return httpx.Response(429, json={"error": "quota"})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(PAYLOAD)}]}}]})

    c = GeminiClient("k", ["primary", "backup"], 5, transport=httpx.MockTransport(handler))
    assert (await c.complete_json("s", "u"))["category"] == "payment_info_query"
    assert len(calls) == 2


async def test_openai_compatible_parses_fenced_json():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer gk"
        assert json.loads(req.content)["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": "```json\n" + json.dumps(PAYLOAD) + "\n```"}}]})

    c = OpenAICompatibleClient("gk", ["llama"], 5, "https://api.groq.test/v1", transport=httpx.MockTransport(handler))
    assert await c.complete_json("s", "u") == PAYLOAD


async def test_errors_raise_llm_error():
    c = OpenAICompatibleClient("gk", ["m"], 5, "https://x.test",
                               transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"choices": [
                                   {"message": {"content": "not json"}}]})))
    with pytest.raises(LLMError):
        await c.complete_json("s", "u")
    with pytest.raises(LLMError):
        await GeminiClient("", ["m"], 5).complete_json("s", "u")
    with pytest.raises(LLMError):
        await DisabledClient().complete_json("s", "u")


def test_build_llm_providers():
    assert build_llm(Settings(_env_file=None, llm_provider="none")).name == "none"
    assert build_llm(Settings(_env_file=None, llm_provider="gemini", llm_api_key="k", llm_model="m")).name == "gemini"
    groq = build_llm(Settings(_env_file=None, llm_provider="groq", llm_api_key="k", llm_model="m"))
    assert groq.base_url == "https://api.groq.com/openai/v1"
