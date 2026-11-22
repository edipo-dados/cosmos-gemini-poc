"""Spike: Cosmos AuthorizationGateway + ToolAdapter gating a poc tool (uses public names exported by runtime.cosmos_runtime)."""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".vendor" / "cosmos"))
from runtime.cosmos_runtime import (AuthorizationGateway, ObjectiveRequest, RuntimeConfig, ToolAdapter, build_services)
from runtime.cosmos_runtime.model import ExecutionState
from runtime.cosmos_runtime.effects import AdapterBoundaryError
from runtime.cosmos_runtime.authorization import AuthorizationBlocked
ACTOR = "cosmos:actor:gemini-agent"
root = Path(tempfile.mkdtemp())
svc = build_services(RuntimeConfig(database_path=root/"rt.sqlite3", environment_ref="cosmos:test"))
intake = svc.intake_objective(ObjectiveRequest(objective="Qual a receita liquida?", requester_ref=ACTOR, execution_actor_ref=ACTOR,
        environment_ref="cosmos:test", idempotency_key="spike-1"))
ep = svc.store.get_episode(intake.episode_id)
svc.store.transition_episode(ep.episode_id, ExecutionState.PREPARING, expected_state=ExecutionState.CREATED)
svc.store.transition_episode(ep.episode_id, ExecutionState.READY, expected_state=ExecutionState.PREPARING)
state = {"capabilities": [{"capability_id":"cap:list_metrics","grantee_refs":[ACTOR],"action":"tool.invoke","decision":"allow",
          "resources":["tool:list_metrics"],"constraints":{},"task_ref":intake.task.task_ref}], "approvals": [], "delegations": []}
gw = AuthorizationGateway(svc, lambda _: state)
tools = ToolAdapter(svc)
tools.register("tool:list_metrics", lambda p: {"metrics": ["net_revenue"], "args": p})
tools.register("tool:drop_everything", lambda p: "should never run")
def call(ref, params):
    eff = gw.new_attempt(episode_id=intake.episode_id, action="tool.invoke", resource_ref=ref, parameters=params)
    try:
        tok = gw.authorize_effect(eff)
        return ("decision", tok.decision.result, tools.execute(tok).output)
    except (AdapterBoundaryError, AuthorizationBlocked) as e:
        return ("blocked", type(e).__name__, str(e))
print("ALLOWED :", call("tool:list_metrics", {"q": "x"}))
print("DENIED  :", call("tool:drop_everything", {}))
import sqlite3
rows = sqlite3.connect(root/"rt.sqlite3").execute("select event_type,count(*) from runtime_events group by 1 order by 1").fetchall()
print(json.dumps(rows))
