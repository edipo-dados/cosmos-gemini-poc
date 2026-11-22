from __future__ import annotations

from fastapi import Header, Request

from agent.tools.errors import ToolError
from app.api.schemas import ID_RE
from app.api.state import AppState


def get_state(request: Request) -> AppState:
    return request.app.state.poc


class InvalidRequest(ToolError):
    """Erro de entrada da API (400)."""


def user_id(x_user_id: str | None = Header(default=None)) -> str:
    if x_user_id is None:
        return "demo"
    if not ID_RE.match(x_user_id):
        raise InvalidRequest("invalid_user_id", "X-User-Id deve casar com ^[A-Za-z0-9_.-]{1,64}$.")
    return x_user_id
