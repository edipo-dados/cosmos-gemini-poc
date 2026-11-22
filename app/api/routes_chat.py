"""`POST /chat` (alias `/ask`): pergunta em linguagem natural respondida pelo Gemini com ferramentas governadas."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request

from agent.gemini.errors import GeminiNotConfigured
from agent.tools.errors import ToolError
from app.api.deps import InvalidRequest, get_state, user_id
from app.api.schemas import ID_RE, MAX_QUESTION, ChatRequest
from app.api.state import AppState

router = APIRouter()


def _chat(body: ChatRequest, request: Request, uid: str, state: AppState) -> dict:
    question = body.question.strip()
    if not 1 <= len(question) <= MAX_QUESTION:
        raise InvalidRequest("invalid_question", f"A pergunta deve ter de 1 a {MAX_QUESTION} caracteres.")
    if body.session_id is not None and not ID_RE.match(body.session_id):
        raise InvalidRequest("invalid_session_id", "session_id deve casar com ^[A-Za-z0-9_.-]{1,64}$.")
    if state.chat is None:
        raise GeminiNotConfigured("GEMINI_API_KEY não está definida no ambiente. O chat está indisponível; "
                                  "as ferramentas continuam acessíveis em POST /tools/{name}.")
    return state.chat.ask(question, uid, body.session_id or str(uuid.uuid4()), request.state.request_id)


@router.post("/chat")
def chat(body: ChatRequest, request: Request, uid: str = Depends(user_id), state: AppState = Depends(get_state)):
    return _chat(body, request, uid, state)


@router.post("/ask")
def ask(body: ChatRequest, request: Request, uid: str = Depends(user_id), state: AppState = Depends(get_state)):
    return _chat(body, request, uid, state)
