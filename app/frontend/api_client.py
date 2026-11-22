"""Cliente HTTP da API FastAPI. O frontend só fala com a API: nunca abre banco nem chama o Gemini."""
from __future__ import annotations
import os
from typing import Any
import httpx

DEFAULT_TIMEOUT = 30.0
CHAT_TIMEOUT = 120.0  # o Gemini pode encadear várias rodadas de ferramentas


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def api_url() -> str:
    return os.environ.get("API_URL", "http://localhost:8000").rstrip("/")


def user_id() -> str:
    return os.environ.get("UI_USER_ID", "demo")


def _request(method: str, path: str, *, params: dict | None = None, json: Any = None, timeout: float = DEFAULT_TIMEOUT) -> Any:
    try:
        resp = httpx.request(method, api_url() + path, params=params, json=json, timeout=timeout,
                             headers={"X-User-Id": user_id()})
    except httpx.TimeoutException as exc:
        raise ApiError("api_timeout", "A API não respondeu a tempo.") from exc
    except httpx.HTTPError as exc:
        raise ApiError("api_unavailable", f"Não foi possível conectar à API em {api_url()}.") from exc
    try:
        body = resp.json()
    except ValueError:
        body = None
    if resp.status_code >= 400:
        err = body.get("error") if isinstance(body, dict) else None
        if isinstance(err, dict):
            raise ApiError(err.get("code", "http_error"), err.get("message", "Erro na API."), resp.status_code)
        raise ApiError("http_error", f"A API respondeu HTTP {resp.status_code}.", resp.status_code)
    return body


def get(path: str, **params) -> Any:
    return _request("GET", path, params={k: v for k, v in params.items() if v is not None})


def post(path: str, payload: Any = None, timeout: float = DEFAULT_TIMEOUT) -> Any:
    return _request("POST", path, json=payload, timeout=timeout)


def health() -> dict:
    return get("/health")


def chat(question: str, session_id: str | None = None) -> dict:
    body: dict = {"question": question}
    if session_id:
        body["session_id"] = session_id
    return post("/chat", body, timeout=CHAT_TIMEOUT)


def query_metric(args: dict) -> dict:
    return post("/tools/query_metric", args)
