"""Transporte HTTP falso para o SDK `google-genai` (httpx.MockTransport). NÃO é o Gemini.

Substitui só a fronteira HTTP: o SDK real monta a requisição (declarações, config, conteúdo) e interpreta a resposta.
O roteiro decide a próxima resposta com base no corpo recebido. Usado para provar o loop de Function Calling sem chave.
"""
from __future__ import annotations

import json
from typing import Callable

import httpx
from google.genai import types

Step = Callable[[dict], dict | httpx.Response] | dict | httpx.Response


def call(name: str, args: dict | None = None) -> dict:
    return {"candidates": [{"content": {"role": "model", "parts": [{"functionCall": {"name": name, "args": args or {}}}]},
                            "finishReason": "STOP"}], "modelVersion": "scripted-fake"}


def calls(*items: tuple[str, dict]) -> dict:
    parts = [{"functionCall": {"name": n, "args": a}} for n, a in items]
    return {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}], "modelVersion": "scripted-fake"}


def text(t: str) -> dict:
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": t}]}, "finishReason": "STOP"}],
            "modelVersion": "scripted-fake"}


def blocked() -> dict:
    return {"promptFeedback": {"blockReason": "SAFETY"}, "modelVersion": "scripted-fake"}


def http_error(code: int, status: str, message: str) -> httpx.Response:
    return httpx.Response(code, json={"error": {"code": code, "message": message, "status": status}})


def function_responses(body: dict) -> list[dict]:
    """Todas as respostas de função enviadas pelo cliente ao modelo, na ordem."""
    out = []
    for content in body.get("contents", []):
        for part in content.get("parts", []):
            fr = part.get("functionResponse") or part.get("function_response")
            if fr:
                out.append(fr)
    return out


def last_response(body: dict) -> dict:
    return function_responses(body)[-1]["response"]


class ScriptedGemini:
    """Roteiro mutável: cada requisição a :generateContent consome o próximo passo."""

    def __init__(self):
        self.script: list[Step] = []
        self.requests: list[dict] = []
        self.urls: list[str] = []
        self.api_keys: list[str | None] = []

    def load(self, *steps: Step) -> "ScriptedGemini":
        self.script = list(steps)
        self.requests.clear()
        self.urls.clear()
        self.api_keys.clear()
        return self

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.requests.append(body)
        self.urls.append(str(request.url))
        self.api_keys.append(request.headers.get("x-goog-api-key"))
        if not self.script:
            return http_error(500, "INTERNAL", "roteiro vazio")
        step = self.script.pop(0)
        if callable(step):
            step = step(body)
        return step if isinstance(step, httpx.Response) else httpx.Response(200, json=step)

    def http_options(self) -> types.HttpOptions:
        return types.HttpOptions(httpx_client=httpx.Client(transport=httpx.MockTransport(self.handler)))
