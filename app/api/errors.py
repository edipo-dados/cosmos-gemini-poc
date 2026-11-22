"""Formato único de erro `{"error": {"code", "message"}}` e mapeamento de exceções."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from agent.gemini.errors import GeminiError
from agent.tools.errors import ToolError
from agent.tools.schemas import HTTP_STATUS

log = logging.getLogger("poc.api")


def error_response(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, **extra}})


def register_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"] if p != "body") or "corpo"
        return error_response(400, "invalid_request", f"Requisição inválida em '{where}': {first['msg']}")

    @app.exception_handler(GeminiError)
    async def _gemini(_: Request, exc: GeminiError):
        return error_response(exc.http_status, exc.code, exc.message)

    @app.exception_handler(ToolError)
    async def _tool(_: Request, exc: ToolError):
        return error_response(HTTP_STATUS.get(exc.code, 500), exc.code, exc.message)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.error("erro não tratado: %s", type(exc).__name__, exc_info=True)
        return error_response(500, "internal_error", "Erro interno.")
