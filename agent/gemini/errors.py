"""Erros da camada Gemini e mapeamento dos erros do SDK `google-genai` (docs/ARCHITECTURE.md, seção 5.1)."""
from __future__ import annotations

from google.genai import errors as genai_errors


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


def is_retryable(exc: Exception) -> bool:
    """429 e 5xx do SDK; falha de rede (httpx) também conta como indisponibilidade transitória."""
    if isinstance(exc, genai_errors.APIError):
        return exc.code == 429 or (isinstance(exc.code, int) and exc.code >= 500)
    return type(exc).__module__.split(".")[0] in ("httpx", "httpx2", "httpcore")


def map_error(exc: Exception) -> GeminiError:
    """Nunca inclui a chave: só o código HTTP e o status textual."""
    if isinstance(exc, genai_errors.APIError):
        code = exc.code
        text = f"{exc.status or ''} {getattr(exc, 'message', '') or ''}".lower()
        if code in (401, 403) or (code == 400 and "api key" in text):
            return GeminiAuthFailed("A chave GEMINI_API_KEY foi recusada pelo Gemini. Corrija a chave no ambiente.")
        if code == 404:
            return GeminiModelInvalid("O modelo configurado em GEMINI_MODEL não foi encontrado. Corrija o nome do modelo.")
        return GeminiUnavailable(f"O Gemini está indisponível no momento (HTTP {code}). Tente novamente.")
    return GeminiUnavailable(f"Falha de comunicação com o Gemini ({type(exc).__name__}). Tente novamente.")
