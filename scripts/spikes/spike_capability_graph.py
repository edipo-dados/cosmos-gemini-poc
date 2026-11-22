"""Spike (Phase 1 gate): a `capability` node written in graph.json drives the Cosmos AuthorizationGateway.

Proves, in a throwaway World (temp dir + git init + `cosmos init`):
  1. a `tool.invoke` capability node with ExternalLocator resources and grantee_refs validates (validate_graph == []);
  2. the node maps to the authority_state format of AuthorizationGateway
     (resources[0].uri == resource_ref passed to new_attempt);
  3. a tool without a capability node is denied (no_applicable_allow);
  4. the episode lifecycle used by the design (CREATED -> PREPARING -> READY -> RUNNING -> COMPLETED).
Run: .venv/bin/python scripts/spikes/spike_capability_graph.py
"""
import json, subprocess, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / ".vendor" / "cosmos"))
from tools.validate_ontology import validate_graph
from tools.reference_repository_projection import stable_cosmos_ref
from runtime.cosmos_runtime import AuthorizationGateway, ObjectiveRequest, RuntimeConfig, ToolAdapter, build_services
from runtime.cosmos_runtime.model import ExecutionState
from runtime.cosmos_runtime.authorization import AuthorizationBlocked
from runtime.cosmos_runtime.effects import AdapterBoundaryError

SYSTEM = "poc-tools"
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

agent = node("actor:poc.agent", node_type="actor", schema="cosmos.actor/1", actor_type="service",
             display_name="poc.agent", implementation="poc-gemini-orchestrator")
user = node("actor:poc.user", node_type="actor", schema="cosmos.actor/1", actor_type="human", display_name="poc.user")
caps = [node(f"cap:tool:{t}", node_type="capability", schema="cosmos.capability/1", action="tool.invoke", decision="allow",
             grantee_refs=[agent["id"]], resources=[{"system": SYSTEM, "uri": f"tool:{t}"}], display_name=f"tool.invoke {t}")
        for t in ("list_metrics",)]
ids = {r["id"] for r in [agent, user, *caps]}
new = [r for r in graph if r["id"] not in ids] + [agent, user, *caps]
errors = validate_graph(new)
print("validate_graph errors:", errors)
assert errors == []
gp.write_text(json.dumps(new, indent=1))

def authority_state(task_ref):
    out = []
    for r in json.loads(gp.read_text()):
        if r.get("node_type") == "capability" and r.get("decision") == "allow":
            out.append({"capability_id": r["id"], "grantee_refs": r["grantee_refs"], "action": r["action"], "decision": "allow",
                        "resources": [x["uri"] for x in r["resources"] if x["system"] == SYSTEM],
                        "constraints": r.get("constraints", {}), "task_ref": task_ref})
    return {"capabilities": out, "approvals": [], "delegations": []}

svc = build_services(RuntimeConfig(database_path=w / ".cosmos" / "rt-spike.sqlite3", environment_ref="cosmos:test"))
intake = svc.intake_objective(ObjectiveRequest(objective="Qual a receita liquida?", requester_ref=user["id"],
                                               execution_actor_ref=agent["id"], environment_ref="cosmos:test", idempotency_key="spike-cap-1"))
eid = intake.episode_id
svc.store.transition_episode(eid, ExecutionState.PREPARING, expected_state=ExecutionState.CREATED)
svc.store.transition_episode(eid, ExecutionState.READY, expected_state=ExecutionState.PREPARING)
gw = AuthorizationGateway(svc, lambda _e: authority_state(intake.task.task_ref))
tools = ToolAdapter(svc)
tools.register("tool:list_metrics", lambda p: {"metrics": ["net_revenue"]})
tools.register("tool:query_metric", lambda p: "must be denied: no capability node")

def call(ref):
    eff = gw.new_attempt(episode_id=eid, action="tool.invoke", resource_ref=ref, parameters={})
    try:
        tok = gw.authorize_effect(eff)
        return ("ALLOWED", tools.execute(tok).output)
    except (AdapterBoundaryError, AuthorizationBlocked) as e:
        return ("DENIED", type(e).__name__, str(e))
print("tool:list_metrics ->", call("tool:list_metrics"))
print("tool:query_metric ->", call("tool:query_metric"))
print("tool:list_metrics again (2nd attempt, same episode) ->", call("tool:list_metrics"))
svc.store.transition_episode(eid, ExecutionState.RUNNING, expected_state=ExecutionState.READY)
svc.store.transition_episode(eid, ExecutionState.COMPLETED, expected_state=ExecutionState.RUNNING)
print("final episode state:", svc.store.get_episode(eid).state.value)
