"""`POST /tools/{name}` e `GET /evidence/{query_id}`: as 7 ferramentas passam pelo ToolExecutor (Cosmos + auditoria)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from app.api.deps import get_state, user_id
from app.api.state import AppState

router = APIRouter()


@router.post("/tools/{name}")
def call_tool(name: str, body: Any = Body(default=None), uid: str = Depends(user_id), state: AppState = Depends(get_state)):
    outcome = state.executor.execute(name, {} if body is None else body, uid)
    return JSONResponse(status_code=outcome.http_status, content=outcome.payload)


@router.get("/evidence/{query_id}")
def evidence(query_id: str, uid: str = Depends(user_id), state: AppState = Depends(get_state)):
    """Evidência de uma consulta (mesma ferramenta `get_evidence`, com autorização no Cosmos e auditoria)."""
    outcome = state.executor.execute("get_evidence", {"query_id": query_id}, uid)
    return JSONResponse(status_code=outcome.http_status, content=outcome.payload)
