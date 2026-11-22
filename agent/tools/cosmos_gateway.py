"""Integração com o runtime do Cosmos: episódio por pergunta, `AuthorizationGateway` e `ToolAdapter` (tool.invoke).

O Cosmos autoriza e registra a FERRAMENTA. Quem executa a consulta é o Query Engine, dentro do handler do executor
(docs/ARCHITECTURE.md, seção 5.3). O `threading.Lock` protege só operações no SQLiteRuntimeStore.
API interna usada: `store.transition_episode` (não consta em runtime/README.md; coberta por teste).
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from pathlib import Path

from runtime.cosmos_runtime import AuthorizationGateway, ObjectiveRequest, RuntimeConfig, ToolAdapter, build_services
from runtime.cosmos_runtime.authorization import AuthorizationBlocked
from runtime.cosmos_runtime.effects import AdapterBoundaryError
from runtime.cosmos_runtime.model import ExecutionState
from tools.reference_repository_projection import stable_cosmos_ref

from .errors import ToolError
from .schemas import TOOL_NAMES

log = logging.getLogger("poc.cosmos")
TOOL_SYSTEM = "poc-tools"
__all__ = ["CosmosRuntime", "AuthorizationBlocked", "AdapterBoundaryError", "WorldNotInitialized"]


class WorldNotInitialized(RuntimeError):
    code = "world_not_initialized"


class CosmosRuntime:
    def __init__(self, world_dir: Path | str):
        self.world = Path(world_dir)
        manifest, self.graph_path = self.world / "cosmos.environment.json", self.world / ".cosmos" / "graph.json"
        if not manifest.is_file() or not self.graph_path.is_file():
            raise WorldNotInitialized("world_not_initialized: faltam cosmos.environment.json ou .cosmos/graph.json "
                                      "(rode scripts/bootstrap.sh e make sync).")
        self.environment_ref = json.loads(manifest.read_text(encoding="utf-8"))["environment_id"]
        self.agent_id = stable_cosmos_ref("actor:poc.agent")
        self.user_id = stable_cosmos_ref("actor:poc.user")
        graph = self._graph()
        ids = {r.get("id") for r in graph if isinstance(r, dict)}
        if self.agent_id not in ids or self.user_id not in ids:
            raise WorldNotInitialized("Atores poc.agent e poc.user ausentes do grafo. Rode make sync.")
        self.lock = threading.Lock()  # protege somente o SQLiteRuntimeStore
        self.services = build_services(RuntimeConfig(database_path=self.world / ".cosmos" / "runtime.sqlite3",
                                                     environment_ref=self.environment_ref))
        self.adapter = ToolAdapter(self.services)
        self.pending: dict[str, dict] = {}
        self._pending_lock = threading.Lock()
        for name in TOOL_NAMES:
            self.adapter.register(f"tool:{name}", self._handler)
        self.gateway = AuthorizationGateway(self.services, self._provider)

    # ---- grafo e provider (fail closed) ----
    def _graph(self) -> list[dict]:
        return json.loads(self.graph_path.read_text(encoding="utf-8"))

    def _provider(self, episode_id: str) -> dict:
        try:
            task_ref = self.services.store.get_episode(episode_id).task_ref
            caps = [{"capability_id": r["id"], "grantee_refs": r["grantee_refs"], "action": r["action"], "decision": "allow",
                     "resources": [x["uri"] for x in r.get("resources", []) if x.get("system") == TOOL_SYSTEM],
                     "constraints": {}, "task_ref": task_ref}
                    for r in self._graph() if r.get("node_type") == "capability" and r.get("decision") == "allow"]
        except Exception:  # noqa: BLE001 - qualquer falha de leitura nega tudo
            log.exception("provider de capacidades falhou; negando tudo")
            caps = []
        return {"capabilities": caps, "approvals": [], "delegations": []}

    # ---- handoff do resumo por query_id (o handler nunca reexecuta a consulta) ----
    def put_pending(self, query_id: str, summary: dict) -> None:
        with self._pending_lock:
            self.pending[query_id] = summary

    def drop_pending(self, query_id: str) -> None:
        with self._pending_lock:
            self.pending.pop(query_id, None)

    def _handler(self, params: dict) -> dict:
        qid = params.get("query_id")
        with self._pending_lock:
            summary = self.pending.pop(qid, None)
        if summary is None:
            raise AdapterBoundaryError(f"resumo ausente para query_id={qid}")
        return {"query_id": qid, "row_count": summary["row_count"], "status": summary["status"]}

    # ---- episódios ----
    def open_episode(self, objective: str, idempotency_key: str | None = None) -> str:
        try:
            with self.lock:
                intake = self.services.intake_objective(ObjectiveRequest(
                    objective=objective, requester_ref=self.user_id, execution_actor_ref=self.agent_id,
                    environment_ref=self.environment_ref, idempotency_key=idempotency_key or f"tool:{uuid.uuid4()}"))
                if not intake.created:
                    raise ToolError("cosmos_runtime_unavailable", "Episódio já existente para a mesma chave de idempotência.")
                eid = intake.episode_id
                store = self.services.store
                store.transition_episode(eid, ExecutionState.PREPARING, expected_state=ExecutionState.CREATED)
                store.transition_episode(eid, ExecutionState.READY, expected_state=ExecutionState.PREPARING)
            return eid
        except ToolError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("falha ao abrir episódio no Cosmos: %s", type(exc).__name__, exc_info=True)
            raise ToolError("cosmos_runtime_unavailable", "Runtime do Cosmos indisponível.") from exc

    def close_episode(self, episode_id: str, ok: bool) -> None:
        """ok: READY -> RUNNING -> COMPLETED; senão READY -> FAILED. Falha aqui é registrada e não derruba a resposta."""
        try:
            with self.lock:
                store = self.services.store
                if ok:
                    store.transition_episode(episode_id, ExecutionState.RUNNING, expected_state=ExecutionState.READY)
                    store.transition_episode(episode_id, ExecutionState.COMPLETED, expected_state=ExecutionState.RUNNING)
                else:
                    store.transition_episode(episode_id, ExecutionState.FAILED, expected_state=ExecutionState.READY)
        except Exception:  # noqa: BLE001
            log.error("falha ao fechar episódio %s", episode_id, exc_info=True)

    def authorize(self, episode_id: str, tool: str, query_id: str, arguments: dict):
        """Devolve o AuthorizedEffect. Negação -> ToolError tool_not_authorized; outra falha -> cosmos_runtime_unavailable."""
        try:
            with self.lock:
                effect = self.gateway.new_attempt(episode_id=episode_id, action="tool.invoke", resource_ref=f"tool:{tool}",
                                                  parameters={"query_id": query_id, "arguments": arguments})
                return self.gateway.authorize_effect(effect)
        except AuthorizationBlocked as exc:
            log.warning("ferramenta %s negada pelo gateway do Cosmos", tool)
            raise ToolError("tool_not_authorized", f"A ferramenta '{tool}' não está autorizada no Cosmos.") from exc
        except Exception as exc:  # noqa: BLE001
            log.error("falha no gateway do Cosmos: %s", type(exc).__name__, exc_info=True)
            raise ToolError("cosmos_runtime_unavailable", "Runtime do Cosmos indisponível.") from exc

    def record(self, authorized) -> None:
        with self.lock:
            self.adapter.execute(authorized)

    def health(self) -> str:
        try:
            with self.lock:
                return "ok" if self.services.store.health().get("status") == "ok" else "unavailable"
        except Exception:  # noqa: BLE001
            return "unavailable"
