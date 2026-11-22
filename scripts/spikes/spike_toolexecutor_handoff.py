"""Spike (revisao rodada 3, achados 1-3): prova o handoff do resultado ao handler do ToolAdapter,
a ordem validacao-de-esquema -> autorizacao -> validacao-de-dominio, e o tratamento de falhas do
SemanticReader / tool_explain com caminho explicito do grafo.

Mundo descartavel (temp dir + git init + `cosmos init`). Nao usa Gemini nem DuckDB: o "Query Engine" e um stub.
Run: .venv/bin/python scripts/spikes/spike_toolexecutor_handoff.py
"""
import json, os, subprocess, sys, tempfile, threading, uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / ".vendor" / "cosmos"))
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tools.validate_ontology import validate_graph
from tools.reference_repository_projection import stable_cosmos_ref
from tools import cosmos_mcp_server as mcp
from runtime.cosmos_runtime import AuthorizationGateway, ObjectiveRequest, RuntimeConfig, ToolAdapter, build_services
from runtime.cosmos_runtime.model import ExecutionState
from runtime.cosmos_runtime.authorization import AuthorizationBlocked
from runtime.cosmos_runtime.effects import AdapterBoundaryError

SYSTEM = "poc-tools"
TOOLS = ("query_metric", "explain_metric")
w = Path(tempfile.mkdtemp())
subprocess.run(["git", "init", "-q"], cwd=w, check=True)
(w / "README.md").write_text("# t\n")
subprocess.run(["git", "add", "."], cwd=w, check=True)
subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"], cwd=w, check=True)
subprocess.run([str(Path(sys.executable).parent / "cosmos"), "init", str(w)], check=True, capture_output=True)
gp = w / ".cosmos" / "graph.json"
graph = json.loads(gp.read_text())
init_actor = next(r for r in graph if r.get("node_type") == "actor")["id"]
now = "2026-01-01T00:00:00Z"
prov = [{"relation": "created_by", "source": init_actor}]

def node(key, **kw):
    d = {"record_type": "node", "id": stable_cosmos_ref(key), "authority": {"class": "cosmos"},
         "provenance": prov, "temporal": {"created_at": now}}
    d.update(kw)
    return d

agent = node("actor:poc.agent", node_type="actor", schema="cosmos.actor/1", actor_type="service", display_name="poc.agent",
             implementation="poc-gemini-orchestrator")
user = node("actor:poc.user", node_type="actor", schema="cosmos.actor/1", actor_type="human", display_name="poc.user")
caps = [node(f"cap:tool:{t}", node_type="capability", schema="cosmos.capability/1", action="tool.invoke", decision="allow",
             grantee_refs=[agent["id"]], resources=[{"system": SYSTEM, "uri": f"tool:{t}"}], display_name=f"tool.invoke {t}")
        for t in TOOLS]
metric = node("metric:net_revenue", node_type="entity", schema="cosmos.node/1", entity_type="poc.metric",
              display_name="net_revenue", description="Receita liquida", aliases=["Faturamento liquido"],
              extensions={"poc.metric": {"version": "1.0.0"}})
GRAPH_WITH_METRIC = graph + [agent, user, *caps, metric]
errs = validate_graph(GRAPH_WITH_METRIC)
print("validate_graph errors:", errs)
assert errs == []
gp.write_text(json.dumps(GRAPH_WITH_METRIC, indent=1))

# ---------- SemanticReader minimo: caminho explicito, sem load_graph ----------
class SemanticCatalogUnavailable(Exception):
    code = "semantic_catalog_unavailable"

def read_semantic_graph(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SemanticCatalogUnavailable(f"graph ilegivel: {type(e).__name__}") from e
    if not isinstance(data, list) or not any(r.get("entity_type") == "poc.metric" for r in data if isinstance(r, dict)):
        raise SemanticCatalogUnavailable("graph sem nos poc.metric")
    return data

def explain_adapter(path: Path, metric_name: str) -> dict:
    g = read_semantic_graph(path)
    res = mcp.tool_explain(g, {"id": stable_cosmos_ref(f"metric:{metric_name}")})
    if "error" in res:  # tool_explain devolve dict de erro como retorno normal
        raise RuntimeError(f"internal_error: divergencia YAML x grafo ({res['error'][:40]}...)")
    return res

# ---------- ToolExecutor minimo ----------
class QueryMetricArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    limit: int = Field(default=100, ge=1, le=1000)

CATALOG = {"net_revenue"}
svc = build_services(RuntimeConfig(database_path=w / ".cosmos" / "rt-spike.sqlite3", environment_ref="cosmos:test"))
LOCK = threading.Lock()
PENDING: dict[str, dict] = {}
ENGINE_CALLS = []   # prova: o "Query Engine" roda uma vez e fora do lock

def handler(params: dict):
    # Handler registrado uma vez: so recebe `parameters`. Resumo vem de PENDING por query_id.
    qid = params.get("query_id")
    try:
        s = PENDING.pop(qid)
    except KeyError as e:
        raise AdapterBoundaryError(f"resumo ausente para query_id={qid}") from e
    return {"query_id": qid, "row_count": s["row_count"], "status": s["status"]}

tools = ToolAdapter(svc)
tools.register("tool:query_metric", handler)
tools.register("tool:explain_metric", lambda p: {"ok": True})  # registrada mas sem uso aqui
DENY_STATE = {"on": False}

def authority_state(task_ref):
    if DENY_STATE["on"]:
        return {"capabilities": [], "approvals": [], "delegations": []}
    out = []
    for r in json.loads(gp.read_text()):
        if r.get("node_type") == "capability" and r.get("decision") == "allow":
            out.append({"capability_id": r["id"], "grantee_refs": r["grantee_refs"], "action": r["action"], "decision": "allow",
                        "resources": [x["uri"] for x in r["resources"] if x["system"] == SYSTEM],
                        "constraints": r.get("constraints", {}), "task_ref": task_ref})
    return {"capabilities": out, "approvals": [], "delegations": []}

def open_episode():
    intake = svc.intake_objective(ObjectiveRequest(objective="tool:query_metric", requester_ref=user["id"],
             execution_actor_ref=agent["id"], environment_ref="cosmos:test", idempotency_key=f"tool:{uuid.uuid4()}"))
    eid = intake.episode_id
    svc.store.transition_episode(eid, ExecutionState.PREPARING, expected_state=ExecutionState.CREATED)
    svc.store.transition_episode(eid, ExecutionState.READY, expected_state=ExecutionState.PREPARING)
    return eid, intake.task.task_ref

def counts(eid):
    ev = [e.event_type for e in svc.store.list_events(eid)]
    return {"decision": sum("authorization.decision" in t for t in ev), "adapter_result": sum("adapter.result" in t for t in ev)}

def run_tool(raw_args: dict) -> dict:
    """Ordem: 1) esquema Pydantic (antes do gateway) 2) new_attempt+authorize 3) dominio+execucao 4) adapter.execute."""
    try:                                              # passo 1
        args = QueryMetricArgs(**raw_args)
    except ValidationError:
        return {"status": "rejected", "error_code": "invalid_arguments", "cosmos_decision_id": None, "episode": None}
    eid, task_ref = open_episode()
    gw = AuthorizationGateway(svc, lambda _e: authority_state(task_ref))
    qid = str(uuid.uuid4())
    params = {"query_id": qid, "arguments": args.model_dump()}
    try:                                              # passo 2 (lock curto)
        with LOCK:
            eff = gw.new_attempt(episode_id=eid, action="tool.invoke", resource_ref="tool:query_metric", parameters=params)
            authorized = gw.authorize_effect(eff)
    except AuthorizationBlocked:
        return {"status": "rejected", "error_code": "tool_not_authorized", "cosmos_decision_id": None, "episode": eid}
    # passo 3 (fora do lock): validacao de dominio + "Query Engine"
    if args.metric not in CATALOG:
        summary = {"row_count": 0, "status": "rejected"}; code = "unknown_metric"
    else:
        ENGINE_CALLS.append(qid); assert not LOCK.locked()
        summary = {"row_count": 3, "status": "ok"}; code = None
    PENDING[qid] = summary
    with LOCK:                                        # passo 4: toda chamada autorizada chama execute
        res = tools.execute(authorized)
    assert res.output["query_id"] == qid
    return {"status": summary["status"], "error_code": code, "cosmos_decision_id": authorized.decision.decision_id,
            "episode": eid, "output": res.output}

print("\n== Achado 1: handoff por query_id ==")
r = run_tool({"metric": "net_revenue"})
print("ok:", r["status"], r["output"], "| counts", counts(r["episode"]), "| PENDING vazio:", not PENDING)
assert r["output"]["row_count"] == 3 and counts(r["episode"]) == {"decision": 1, "adapter_result": 1}
r = run_tool({"metric": "metrica_x"})
print("unknown_metric:", r["status"], r["error_code"], r["output"], "| counts", counts(r["episode"]))
assert counts(r["episode"]) == {"decision": 1, "adapter_result": 1} and r["output"]["row_count"] == 0
print("engine calls (so a valida):", len(ENGINE_CALLS))
assert len(ENGINE_CALLS) == 1
# chave ausente em PENDING -> AdapterBoundaryError
eid, tr = open_episode()
gw = AuthorizationGateway(svc, lambda _e: authority_state(tr))
tok = gw.authorize_effect(gw.new_attempt(episode_id=eid, action="tool.invoke", resource_ref="tool:query_metric",
                                         parameters={"query_id": "inexistente", "arguments": {}}))
try:
    tools.execute(tok); print("FALHOU: esperava AdapterBoundaryError"); sys.exit(1)
except AdapterBoundaryError as e:
    print("pending ausente ->", type(e).__name__, "|", e)

print("\n== Achado 2: ordem validacao x autorizacao ==")
n_before = len(svc.store.list_events(eid))
r = run_tool({"metric": "net_revenue", "campo_extra": 1})
print("campo extra:", r["status"], r["error_code"], "| cosmos_decision_id =", r["cosmos_decision_id"], "| episodio aberto:", r["episode"])
assert r["error_code"] == "invalid_arguments" and r["cosmos_decision_id"] is None and r["episode"] is None
DENY_STATE["on"] = True
r = run_tool({"metric": "net_revenue"})
DENY_STATE["on"] = False
print("sem capacidade:", r["status"], r["error_code"], "| engine calls ainda:", len(ENGINE_CALLS))
assert r["error_code"] == "tool_not_authorized" and len(ENGINE_CALLS) == 1

print("\n== Achado 3: SemanticReader / tool_explain ==")
res = explain_adapter(gp, "net_revenue")
print("explain net_revenue: chaves", sorted(res)[:4], "| 'error' in res:", "error" in res)
assert "error" not in res
print("tool_explain com id ausente (retorno normal, sem excecao):", mcp.tool_explain(GRAPH_WITH_METRIC, {"id": "x"}))
try:
    explain_adapter(gp, "metrica_fantasma"); sys.exit("FALHOU")
except RuntimeError as e:
    print("adaptador converte erro ->", e)
empty = w / "vazio.json"; empty.write_text("[]")
broken = w / "quebrado.json"; broken.write_text("{nao e json")
nometric = w / "sem_metrica.json"; nometric.write_text(json.dumps(graph))
for label, p in (("ausente", w / "nao_existe.json"), ("ilegivel", broken), ("vazio", empty), ("sem poc.metric", nometric)):
    try:
        read_semantic_graph(p); sys.exit("FALHOU " + label)
    except SemanticCatalogUnavailable as e:
        print(f"SemanticReader {label:15s} -> {e.code} ({e})")
print("load_graph() do Cosmos com JSON quebrado e COSMOS_GRAPH explicito ->", end=" ")
os.environ["COSMOS_GRAPH"] = str(broken)
print(mcp.load_graph(), "(engole o erro; por isso o SemanticReader nao o usa)")
# Teste do MCP em subprocesso com COSMOS_GRAPH e cwd fixos
os.environ.pop("COSMOS_GRAPH")
srv = REPO / ".vendor" / "cosmos" / "tools" / "cosmos_mcp_server.py"
code = ("import json,sys;sys.path.insert(0,%r);from tools import cosmos_mcp_server as m;"
        "g=m.load_graph();print(json.dumps({'count':sum(1 for r in g if r.get('entity_type')=='poc.metric'),'path':str(m.resolve_graph_path())}))") % str(REPO / ".vendor" / "cosmos")
out = subprocess.run([sys.executable, "-c", code], cwd=w, env={**os.environ, "COSMOS_GRAPH": str(gp)}, capture_output=True, text=True)
print("subprocesso (cwd=world, COSMOS_GRAPH explicito):", out.stdout.strip(), out.stderr.strip()[:200])
assert json.loads(out.stdout)["count"] > 0
print("\n== Rodada 4, achado 1: falha de formato e sempre invalid_arguments (esquema, antes do gateway) ==")
from uuid import UUID
class ShowSqlArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_id: UUID
class SearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=200)
def schema_step(model, raw):
    # mesmo passo 1 de run_tool: falha de esquema nunca abre episodio nem chama o gateway
    try:
        model(**raw); return None
    except ValidationError:
        return {"status": "rejected", "error_code": "invalid_arguments", "cosmos_decision_id": None}
ev_before = len(svc.store.list_events(eid))
for label, model, raw in (("show_sql query_id='abc'", ShowSqlArgs, {"query_id": "abc"}),
                          ("search_concepts query=''", SearchArgs, {"query": ""}),
                          ("query_metric metric='X-1'", QueryMetricArgs, {"metric": "X-1"})):
    r = schema_step(model, raw)
    print(f"{label:28s} ->", r)
    assert r == {"status": "rejected", "error_code": "invalid_arguments", "cosmos_decision_id": None}
assert schema_step(ShowSqlArgs, {"query_id": str(uuid.uuid4())}) is None   # UUID valido passa ao gateway
assert len(svc.store.list_events(eid)) == ev_before                       # nenhum evento Cosmos novo
# unknown_metric (passou no regex, ausente do catalogo) e dominio: 1 decisao + 1 adapter.result (ja provado acima)
r = run_tool({"metric": "metrica_inexistente"})
assert r["error_code"] == "unknown_metric" and counts(r["episode"]) == {"decision": 1, "adapter_result": 1}
print("unknown_metric (dominio):", r["error_code"], counts(r["episode"]))
print("\nOK")
