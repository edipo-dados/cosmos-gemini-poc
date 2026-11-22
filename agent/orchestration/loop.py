"""Loop manual de Function Calling: Gemini pede ferramentas, o ToolExecutor as executa (Cosmos + Query Engine + auditoria) e
a resposta de cada função volta ao modelo. Máximo de 6 iterações com chamada de ferramenta por pergunta."""
from __future__ import annotations

import logging
import uuid

from google.genai import types

from agent.gemini.client import LLMClient, is_blocked
from agent.gemini.errors import GeminiUnavailable
from agent.tools.cosmos_gateway import CosmosRuntime
from agent.tools.errors import ToolError
from agent.tools.executor import ToolExecutor, ToolOutcome
from app.services.audit import AuditStore

from .session import SessionStore

log = logging.getLogger("poc.chat")
MAX_ITERATIONS = 6
FATAL_CODES = {"cosmos_runtime_unavailable", "semantic_catalog_unavailable", "audit_failed"}
BLOCKED_MESSAGE = "A resposta foi bloqueada pelos filtros de segurança do Gemini. Reformule a pergunta."
INCOMPLETE_MESSAGE = (f"Não consegui concluir a análise dentro do limite de {MAX_ITERATIONS} rodadas de ferramentas. "
                      "Tente uma pergunta mais específica.")


def _text_of(content: types.Content | None) -> str:
    parts = (content.parts or []) if content else []
    return "".join(p.text for p in parts if p.text and not p.thought).strip()


def _evidence(o: ToolOutcome) -> dict:
    row = o.audit_row or {}
    ev = row.get("evidence") or {}
    result = row.get("result") or {}
    return {"query_id": o.query_id, "tool": o.tool, "status": o.status, "error_code": o.error_code,
            "metric": row.get("metric"), "business_name": ev.get("business_name"), "metric_version": ev.get("metric_version"),
            "dimensions": row.get("dimensions"), "filters": row.get("filters"), "rules": ev.get("rules"),
            "sql": row.get("sql_text"), "sql_params": row.get("sql_params"), "source": row.get("source"),
            "catalog_version": row.get("catalog_version"), "etl_run_id": row.get("etl_run_id"),
            "row_count": row.get("row_count"), "columns": result.get("columns"), "rows": result.get("rows"),
            "truncated": result.get("truncated"), "cosmos_episode_id": o.episode_id, "cosmos_decision_id": o.decision_id,
            "error": ev.get("error")}


class ChatOrchestrator:
    def __init__(self, llm: LLMClient, executor: ToolExecutor, runtime: CosmosRuntime, audit: AuditStore,
                 sessions: SessionStore | None = None, max_iterations: int = MAX_ITERATIONS):
        self.llm, self.executor, self.runtime, self.audit = llm, executor, runtime, audit
        self.sessions = sessions or SessionStore()
        self.max_iterations = max_iterations

    def ask(self, question: str, user_id: str, session_id: str, request_id: str) -> dict:
        turn_id = str(uuid.uuid4())
        self.audit.insert_turn(turn_id, user_id, session_id, question, request_id)
        episode_id: str | None = None
        try:
            episode_id = self.runtime.open_episode(question, idempotency_key=turn_id)
            status, answer, calls, queries = self._loop(question, user_id, session_id, turn_id, episode_id)
        except Exception:
            self._close(turn_id, episode_id, "error", None, ok=False)
            raise
        self._close(turn_id, episode_id, status, answer, ok=True)
        if status == "ok":
            self.sessions.add(session_id, question, answer)
        return {"turn_id": turn_id, "session_id": session_id, "status": status, "answer": answer, "model": self.llm.model,
                "tool_calls": calls, "queries": queries, "cosmos_episode_id": episode_id, "request_id": request_id}

    def _close(self, turn_id: str, episode_id: str | None, status: str, answer: str | None, ok: bool) -> None:
        if episode_id:
            self.runtime.close_episode(episode_id, ok=ok)
        try:
            self.audit.finish_turn(turn_id, status, answer, self.llm.model, episode_id)
        except Exception:  # noqa: BLE001
            log.error("falha ao finalizar chat_turn %s", turn_id, exc_info=True)

    def _loop(self, question, user_id, session_id, turn_id, episode_id):
        contents = [*self.sessions.history(session_id), types.Content(role="user", parts=[types.Part.from_text(text=question)])]
        calls: list[dict] = []
        queries: list[dict] = []
        rounds = 0
        while True:
            response = self.llm.generate(contents, force_tool=rounds == 0)  # 1ª rodada: obriga a consultar ferramentas
            if is_blocked(response):
                return "blocked", BLOCKED_MESSAGE, calls, queries
            cand = (response.candidates or [None])[0]
            if cand is None or cand.content is None:
                raise GeminiUnavailable("O Gemini devolveu uma resposta vazia. Tente novamente.")
            fcalls = [p.function_call for p in (cand.content.parts or []) if p.function_call]
            if not fcalls:
                text = _text_of(cand.content)
                if not text:
                    raise GeminiUnavailable("O Gemini devolveu uma resposta sem texto. Tente novamente.")
                return "ok", text, calls, queries
            if rounds >= self.max_iterations:
                return "incomplete", INCOMPLETE_MESSAGE, calls, queries
            rounds += 1
            contents.append(cand.content)  # preserva o conteúdo do modelo como veio (inclui assinaturas de pensamento)
            parts = []
            for fc in fcalls:
                args = dict(fc.args or {})
                outcome = self.executor.execute(fc.name or "", args, user_id, turn_id, episode_id)
                if outcome.error_code in FATAL_CODES:
                    raise ToolError(outcome.error_code, outcome.payload["error"]["message"])
                calls.append({"tool": outcome.tool, "arguments": args, "query_id": outcome.query_id,
                              "status": outcome.status, "error_code": outcome.error_code, "round": rounds})
                if outcome.tool == "query_metric":
                    queries.append(_evidence(outcome))
                body = {"error": outcome.payload["error"]} if outcome.status != "ok" else {"output": outcome.payload}
                parts.append(types.Part.from_function_response(name=fc.name, response=body))
            contents.append(types.Content(role="user", parts=parts))

