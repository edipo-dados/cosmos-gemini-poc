"""Erros da camada Gemini e mapeamento dos erros do SDK `google-genai` (docs/ARCHITECTURE.md, seção 5.1)."""
from __future__ import annotations
import logging
import os
import re

from google.genai import errors as genai_errors


log = logging.getLogger("poc.gemini")
_GEMINI_KEY = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")
_MAX_LOGGED_MESSAGE = 500
class GeminiError(Exception):
    code = "llm_unavailable"
    http_status = 502

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class GeminiNotConfigured(GeminiError):
    code, http_status = "gemini_not_configured", 503


class GeminiAuthFailed(GeminiError):
    code, http_status = "gemini_auth_failed", 503


class GeminiModelInvalid(GeminiError):
    code, http_status = "gemini_model_invalid", 503


class GeminiUnavailable(GeminiError):
    code, http_status = "llm_unavailable", 502


class GeminiQuotaOrBilling(GeminiError):
    code, http_status = "llm_quota_or_billing", 503
def _redact(text: str) -> str:
    """Remove a chave (valor do ambiente e padrão AIza...) de um texto antes de registrá-lo em log."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        text = text.replace(key, "***")
    return _GEMINI_KEY.sub("***", text)[:_MAX_LOGGED_MESSAGE]
def _log_upstream(exc: genai_errors.APIError) -> None:
    log.warning("Gemini APIError: code=%s status=%s message=%s", exc.code, _redact(str(exc.status or "")),
                _redact(str(getattr(exc, "message", "") or "")))
def is_retryable(exc: Exception) -> bool:
    """429 e 5xx do SDK; falha de rede (httpx) também conta como indisponibilidade transitória."""
    if isinstance(exc, genai_errors.APIError):
        return exc.code == 429 or (isinstance(exc.code, int) and exc.code >= 500)
    return type(exc).__module__.split(".")[0] in ("httpx", "httpx2", "httpcore")


def map_error(exc: Exception) -> GeminiError:
    """Nunca inclui a chave: só o código HTTP e o status textual."""
    if isinstance(exc, genai_errors.APIError):
        code = exc.code
        _log_upstream(exc)
        text = f"{exc.status or ''} {getattr(exc, 'message', '') or ''}".lower()
        if code in (401, 403) or (code == 400 and "api key" in text):
            return GeminiAuthFailed("A chave GEMINI_API_KEY foi recusada pelo Gemini. Corrija a chave no ambiente.")
        if code == 404:
            return GeminiModelInvalid("O modelo configurado em GEMINI_MODEL não foi encontrado. Corrija o nome do modelo.")
        if code in (402, 429):
            return GeminiQuotaOrBilling("O Gemini recusou a chamada por cobrança ou cota (HTTP %s). Verifique o faturamento e a cota "
                                        "do projeto da chave no Google AI Studio / Google Cloud e tente novamente." % code)
        return GeminiUnavailable(f"O Gemini está indisponível no momento (HTTP {code}). Tente novamente.")
    return GeminiUnavailable(f"Falha de comunicação com o Gemini ({type(exc).__name__}). Tente novamente.")
