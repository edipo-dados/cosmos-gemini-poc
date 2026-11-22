"""API FastAPI. Endpoints síncronos (`def`) para que o lock do Cosmos nunca bloqueie o event loop (ARCHITECTURE.md, 5.3)."""
from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from google.genai import types

from app.api import routes_chat, routes_data, routes_read, routes_tools
from app.api.errors import error_response, register_handlers
from app.api.schemas import MAX_BODY_BYTES
from app.api.state import build_state
from app.config import Settings, get_settings
from app.logging_setup import configure_logging

log = logging.getLogger("poc.api")


class BodyLimitMiddleware:
    """ASGI: 413 `payload_too_large` acima de 16 KiB (por Content-Length ou, sem ele, pelo corpo bufferizado)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = dict(scope["headers"]).get(b"content-length")
        too_big = error_response(413, "payload_too_large", f"O corpo excede {MAX_BODY_BYTES} bytes.")
        if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            return await too_big(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return await self.app(scope, receive, send)
            chunks.append(message)
            size += len(message.get("body", b""))
            if size > MAX_BODY_BYTES:
                return await too_big(scope, receive, send)
            if not message.get("more_body"):
                break
        replay = iter(chunks)

        async def replayed():
            return next(replay, {"type": "http.disconnect"})

        await self.app(scope, replayed, send)


def create_app(settings: Settings | None = None, gemini_http_options: types.HttpOptions | None = None) -> FastAPI:
    """`gemini_http_options` permite trocar só o transporte HTTP do SDK (usado por testes com transporte falso)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cfg = settings or get_settings()
        configure_logging("poc", cfg, filename="api.log")
        try:
            app.state.poc = build_state(cfg, gemini_http_options)
        except Exception as exc:
            log.error("pré-requisito da API falhou (%s): %s", getattr(exc, "code", type(exc).__name__), exc)
            raise
        log.info("API iniciada; gemini=%s", "configured" if app.state.poc.llm else "not_configured")
        yield

    app = FastAPI(title="Cosmos Analytics POC", version="0.4.0", lifespan=lifespan)
    app.add_middleware(BodyLimitMiddleware)
    register_handlers(app)

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        return response

    app.include_router(routes_data.router)
    app.include_router(routes_read.router)
    app.include_router(routes_tools.router)
    app.include_router(routes_chat.router)
    return app


app = create_app()
