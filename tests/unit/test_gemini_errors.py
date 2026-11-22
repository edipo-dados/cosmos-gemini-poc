"""Mapeamento de erros do SDK google-genai e novas tentativas. Estes testes NÃO verificam o Gemini."""
from __future__ import annotations

import pytest
from google.genai import errors as genai_errors
from google.genai import types

from agent.gemini.client import GeminiClient, is_blocked
from agent.gemini.errors import (GeminiAuthFailed, GeminiModelInvalid, GeminiNotConfigured, GeminiUnavailable,
                                 map_error)
from support.fake_gemini import ScriptedGemini, blocked, http_error, text

Q = [types.Content(role="user", parts=[types.Part.from_text(text="oi")])]


def _err(cls, code, status):
    return cls(code, {"error": {"code": code, "message": "m", "status": status}})


@pytest.mark.parametrize("exc,expected", [
    (_err(genai_errors.ClientError, 401, "UNAUTHENTICATED"), GeminiAuthFailed),
    (_err(genai_errors.ClientError, 403, "PERMISSION_DENIED"), GeminiAuthFailed),
    (_err(genai_errors.ClientError, 404, "NOT_FOUND"), GeminiModelInvalid),
    (_err(genai_errors.ClientError, 429, "RESOURCE_EXHAUSTED"), GeminiUnavailable),
    (_err(genai_errors.ServerError, 500, "INTERNAL"), GeminiUnavailable),
    (_err(genai_errors.ServerError, 503, "UNAVAILABLE"), GeminiUnavailable),
])
def test_sdk_errors_map_to_stable_codes(exc, expected):
    mapped = map_error(exc)
    assert type(mapped) is expected
    assert (mapped.code, mapped.http_status) == {
        GeminiAuthFailed: ("gemini_auth_failed", 503), GeminiModelInvalid: ("gemini_model_invalid", 503),
        GeminiUnavailable: ("llm_unavailable", 502)}[expected]


def test_400_invalid_api_key_is_auth_failure():
    exc = genai_errors.ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT",
                                                   "message": "API key not valid. Please pass a valid API key."}})
    assert isinstance(map_error(exc), GeminiAuthFailed)


def test_missing_key_or_model_is_not_configured():
    with pytest.raises(GeminiNotConfigured) as e:
        GeminiClient("", "gemini-2.5-flash")
    assert e.value.code == "gemini_not_configured" and e.value.http_status == 503
    with pytest.raises(GeminiNotConfigured):
        GeminiClient("k", "")


def _client(fake):
    sleeps = []
    return GeminiClient("chave-falsa", "m", fake.http_options(), sleep=sleeps.append), sleeps


def test_retries_429_and_5xx_with_backoff_then_succeeds():
    fake = ScriptedGemini().load(http_error(429, "RESOURCE_EXHAUSTED", "q"), http_error(503, "UNAVAILABLE", "x"), text("ok"))
    c, sleeps = _client(fake)
    assert c.generate(Q).text == "ok"
    assert sleeps == [1.0, 2.0] and len(fake.requests) == 3


def test_gives_up_after_two_retries():
    fake = ScriptedGemini().load(*[http_error(500, "INTERNAL", "x")] * 3)
    c, sleeps = _client(fake)
    with pytest.raises(GeminiUnavailable):
        c.generate(Q)
    assert sleeps == [1.0, 2.0] and len(fake.requests) == 3


@pytest.mark.parametrize("code,status,exc", [(401, "UNAUTHENTICATED", GeminiAuthFailed), (404, "NOT_FOUND", GeminiModelInvalid)])
def test_fatal_errors_do_not_retry(code, status, exc):
    fake = ScriptedGemini().load(http_error(code, status, "x"))
    c, sleeps = _client(fake)
    with pytest.raises(exc):
        c.generate(Q)
    assert sleeps == [] and len(fake.requests) == 1


def test_error_message_never_contains_key():
    fake = ScriptedGemini().load(http_error(401, "UNAUTHENTICATED", "bad key chave-falsa"))
    c, _ = _client(fake)
    with pytest.raises(GeminiAuthFailed) as e:
        c.generate(Q)
    assert "chave-falsa" not in str(e.value) and e.value.__cause__ is None


def test_blocked_response_detected():
    fake = ScriptedGemini().load(blocked())
    c, _ = _client(fake)
    assert is_blocked(c.generate(Q)) is True
    fake.load(text("normal"))
    assert is_blocked(c.generate(Q)) is False
