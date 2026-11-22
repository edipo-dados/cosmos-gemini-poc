"""Sync do catálogo YAML para um World real do Cosmos e leitura de volta pelo servidor MCP do Cosmos.

World descartável: git init + commit + `cosmos init` em diretório temporário (o World do projeto não é tocado).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import yaml

from semantic import sync_to_cosmos as sync_mod
from semantic.loader import SEMANTIC_DIR, load_catalog
from semantic.sync_to_cosmos import (OWNER, WorldNotInitialized, actor_id, capability_id, dimension_id, glossary_id,
                                     metric_id, rule_id, sync)
from tools.validate_ontology import validate_graph

ROOT = Path(__file__).resolve().parents[2]
MCP_SERVER = ROOT / ".vendor" / "cosmos" / "tools" / "cosmos_mcp_server.py"
COSMOS_BIN = Path(sys.executable).parent / "cosmos"


def make_world(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "README.md").write_text("# mundo de teste\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit", "-qm", "init"], cwd=path, check=True)
    subprocess.run([str(COSMOS_BIN), "init", str(path)], check=True, capture_output=True)
    return path


class MCP:
    """Cliente mínimo do servidor MCP stdio do Cosmos (somente leitura), com COSMOS_GRAPH e cwd fixos."""

    def __init__(self, world: Path):
        env = {**os.environ, "COSMOS_GRAPH": str(world / ".cosmos" / "graph.json")}
        self.proc = subprocess.Popen([sys.executable, str(MCP_SERVER)], cwd=world, env=env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True)
        self._id = 0
        self.rpc("initialize", {})

    def rpc(self, method: str, params: dict):
        self._id += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}) + "\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())["result"]

    def call(self, tool: str, args: dict) -> dict:
        res = self.rpc("tools/call", {"name": tool, "arguments": args})
        assert res["isError"] is False, res
        return json.loads(res["content"][0]["text"])

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=10)


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


@pytest.fixture(scope="module")
def world(tmp_path_factory, catalog):
    w = make_world(tmp_path_factory.mktemp("cosmos") / "world")
    summary = sync(w, catalog)
    assert summary["validate_graph_errors"] == [] and summary["written"] is True
    return w


@pytest.fixture()
def mcp(world):
    client = MCP(world)
    yield client
    client.close()


def graph_of(world: Path) -> list[dict]:
    return json.loads((world / ".cosmos" / "graph.json").read_text(encoding="utf-8"))


def test_graph_is_valid_for_cosmos(world):
    assert validate_graph(graph_of(world)) == []
    out = subprocess.run([str(COSMOS_BIN), "validate", str(world)], capture_output=True, text=True, check=True)
    assert json.loads(out.stdout)["valid"] is True


def test_mcp_server_reads_real_sync_graph(world, mcp, catalog):
    res = mcp.call("cosmos_query", {"where": {"node_type": "entity"}})
    assert res["count"] > 0  # sem isso, um grafo vazio passaria em silêncio
    kinds: dict[str, int] = {}
    for r in res["records"]:
        kinds[r["entity_type"]] = kinds.get(r["entity_type"], 0) + 1
    assert kinds["poc.metric"] == 8 and kinds["poc.dimension"] == 9
    assert kinds["poc.glossary_term"] == len(catalog.glossary)


def test_metrics_in_cosmos_match_yaml(mcp, catalog):
    for name, m in catalog.metrics.items():
        rec = mcp.call("cosmos_query", {"where": {"id": metric_id(name)}})["records"][0]
        ext = rec["extensions"]["poc.metric"]
        assert rec["display_name"] == name and rec["description"] == m["description"]
        assert m["business_name"] in rec["aliases"]
        for key in ("formula", "owner", "version", "allowed_dimensions", "applicable_filters", "denominator",
                    "status_rule", "time_basis", "tests", "source", "business_name"):
            assert ext[key] == m[key], (name, key)
        assert rec["extensions"]["poc.sync"] == {"owner": OWNER, "catalog_version": catalog.version,
                                                 "source_uri": f"semantic/metrics/{name}.yaml"}
        assert {p["relation"] for p in rec["provenance"]} == {"created_by", "imported_from"}
        imported = next(p for p in rec["provenance"] if p["relation"] == "imported_from")["source"]
        assert imported["uri"] == f"semantic/metrics/{name}.yaml" and imported["revision"] == catalog.version


def test_dimensions_and_glossary_in_cosmos_match_yaml(mcp, catalog):
    for name, d in catalog.dimensions.items():
        rec = mcp.call("cosmos_query", {"where": {"id": dimension_id(name)}})["records"][0]
        assert rec["description"] == d["description"] and rec["extensions"]["poc.dimension"]["type"] == d["type"]
        assert set(rec["extensions"]["poc.dimension"]["allowed_for_metrics"]) == {
            m for m, md in catalog.metrics.items() if name in md["allowed_dimensions"]}
    for t in catalog.glossary:
        rec = mcp.call("cosmos_query", {"where": {"id": glossary_id(t["term"])}})["records"][0]
        assert rec["display_name"] == t["term"] and rec["aliases"] == t["synonyms"] and rec["description"] == t["definition"]
        assert {m["name"] for m in rec["extensions"]["poc.glossary_term"]["maps_to"]} == {r["name"] for r in t["maps_to"]}


def test_cosmos_explain_lists_rules_by_governed_by(mcp, catalog):
    for name in catalog.metrics:
        exp = mcp.call("cosmos_explain", {"id": metric_id(name)})
        governed = [e for e in exp["outgoing_edges"] if e["relation_type"] == "core.governed_by"]
        expected = {rule_id(r["id"]): r["statement"] for r in catalog.rules_for(name)}
        assert {e["target"] for e in governed} == set(expected), name
        statements = {n["id"]: n["statement"] for n in exp["neighbours"] if n.get("knowledge_class") == "rule"}
        assert statements == expected, name


def test_rules_are_active_knowledge(mcp, catalog):
    for r in catalog.rules:
        rec = mcp.call("cosmos_query", {"where": {"id": rule_id(r["id"])}})["records"][0]
        assert rec["knowledge_class"] == "rule" and rec["lifecycle_state"] == "active" and rec["statement"] == r["statement"]


def test_capabilities_are_the_seven_tools(mcp, catalog):
    caps = mcp.call("cosmos_tool", {})
    nodes = caps.get("tools") or caps.get("records") or caps.get("capabilities")
    poc = [c for c in nodes if c.get("extensions", {}).get("poc.sync", {}).get("owner") == OWNER]
    assert {c["resources"][0]["uri"] for c in poc} == {f"tool:{t['name']}" for t in catalog.capabilities["tools"]}
    assert all(c["action"] == "tool.invoke" and c["grantee_refs"] == [actor_id("poc.agent")] for c in poc)


def test_yaml_versions_equal_graph_versions(world, catalog):
    by_id = {r["id"]: r for r in graph_of(world)}
    for name, m in catalog.metrics.items():
        assert by_id[metric_id(name)]["extensions"]["poc.metric"]["version"] == m["version"]
    owned = [r for r in by_id.values() if r.get("extensions", {}).get("poc.sync")]
    assert owned and {r["extensions"]["poc.sync"]["catalog_version"] for r in owned} == {catalog.version}


def test_sync_is_idempotent_and_preserves_foreign_records(world, catalog):
    before = (world / ".cosmos" / "graph.json").read_bytes()
    foreign_before = [r for r in graph_of(world) if not r.get("extensions", {}).get("poc.sync")]
    summary = sync(world, catalog)
    assert summary["written"] is False and summary["changed_records"] == 0
    assert (world / ".cosmos" / "graph.json").read_bytes() == before
    assert len(foreign_before) == summary["preserved_foreign_records"] == 6
    ids = [r["id"] for r in graph_of(world)]
    assert len(ids) == len(set(ids))


def _copy_semantic(tmp_path: Path) -> Path:
    copy = tmp_path / "semantic"
    shutil.copytree(SEMANTIC_DIR, copy, ignore=shutil.ignore_patterns("__pycache__", "*.py"))
    return copy


def test_yaml_change_propagates_to_graph(tmp_path):
    w = make_world(tmp_path / "w")
    sync(w, load_catalog())
    before = graph_of(w)
    copy = _copy_semantic(tmp_path)
    p = copy / "metrics" / "gross_revenue.yaml"
    doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    doc["version"] = "1.1.0"
    doc["owner"] = "Controladoria"
    p.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    changed = load_catalog(copy)
    summary = sync(w, changed)
    after = graph_of(w)
    assert summary["written"] is True and after != before
    rec = next(r for r in after if r["id"] == metric_id("gross_revenue"))
    assert rec["extensions"]["poc.metric"]["version"] == "1.1.0" and rec["extensions"]["poc.metric"]["owner"] == "Controladoria"
    assert "updated_at" in rec["temporal"] and rec["temporal"]["created_at"]
    assert validate_graph(after) == []
    assert len({r["id"] for r in after}) == len(after)


def test_removed_rule_and_synonym_leave_the_graph(tmp_path):
    w = make_world(tmp_path / "w")
    sync(w, load_catalog())
    copy = _copy_semantic(tmp_path)
    rp = copy / "rules" / "business_rules.yaml"
    rules = yaml.safe_load(rp.read_text(encoding="utf-8"))
    rules["rules"] = [r for r in rules["rules"] if r["id"] != "growth_calendar"]
    rp.write_text(yaml.safe_dump(rules, allow_unicode=True), encoding="utf-8")
    gp = copy / "glossary" / "glossary.yaml"
    gl = yaml.safe_load(gp.read_text(encoding="utf-8"))
    next(t for t in gl["terms"] if t["term"] == "Receita")["synonyms"].remove("Faturamento")
    gp.write_text(yaml.safe_dump(gl, allow_unicode=True), encoding="utf-8")
    summary = sync(w, load_catalog(copy))
    graph = graph_of(w)
    ids = {r["id"] for r in graph}
    assert rule_id("growth_calendar") not in ids and summary["removed_stale"] >= 2
    receita = next(r for r in graph if r["id"] == glossary_id("Receita"))
    assert "Faturamento" not in receita["aliases"]
    for r in graph:  # sem arestas órfãs
        if r.get("record_type") == "edge":
            assert r["source"] in ids and r["target"] in ids
    assert validate_graph(graph) == []


def _gateway_decision(world: Path, tool: str) -> str:
    """Usa ToolAdapter + AuthorizationGateway reais do Cosmos, com provider que lê os nós `capability` do grafo."""
    from runtime.cosmos_runtime import AuthorizationGateway, ObjectiveRequest, RuntimeConfig, ToolAdapter, build_services
    from runtime.cosmos_runtime.authorization import AuthorizationBlocked
    from runtime.cosmos_runtime.effects import AdapterBoundaryError
    from runtime.cosmos_runtime.model import ExecutionState

    env = json.loads((world / "cosmos.environment.json").read_text(encoding="utf-8"))["environment_id"]
    svc = build_services(RuntimeConfig(database_path=world / ".cosmos" / f"gw-{uuid.uuid4().hex}.sqlite3", environment_ref=env))
    intake = svc.intake_objective(ObjectiveRequest(objective=f"teste {tool}", requester_ref=actor_id("poc.user"),
                                                   execution_actor_ref=actor_id("poc.agent"), environment_ref=env,
                                                   idempotency_key=f"gw-{uuid.uuid4()}"))
    eid = intake.episode_id
    svc.store.transition_episode(eid, ExecutionState.PREPARING, expected_state=ExecutionState.CREATED)
    svc.store.transition_episode(eid, ExecutionState.READY, expected_state=ExecutionState.PREPARING)

    def provider(_episode):
        caps = [{"capability_id": r["id"], "grantee_refs": r["grantee_refs"], "action": r["action"], "decision": "allow",
                 "resources": [x["uri"] for x in r["resources"] if x["system"] == "poc-tools"], "constraints": {},
                 "task_ref": intake.task.task_ref}
                for r in graph_of(world) if r.get("node_type") == "capability" and r.get("decision") == "allow"]
        return {"capabilities": caps, "approvals": [], "delegations": []}

    gw = AuthorizationGateway(svc, provider)
    adapter = ToolAdapter(svc)
    adapter.register(f"tool:{tool}", lambda params: {"ok": True})
    eff = gw.new_attempt(episode_id=eid, action="tool.invoke", resource_ref=f"tool:{tool}", parameters={})
    try:
        token = gw.authorize_effect(eff)
        adapter.execute(token)
        return "allow"
    except (AuthorizationBlocked, AdapterBoundaryError):
        return "deny"


def test_gateway_follows_synced_capabilities(tmp_path):
    w = make_world(tmp_path / "w")
    sync(w, load_catalog())
    assert _gateway_decision(w, "query_metric") == "allow"
    assert _gateway_decision(w, "execute_sql") == "deny"  # nunca declarada
    copy = _copy_semantic(tmp_path)
    cp = copy / "rules" / "agent_capabilities.yaml"
    caps = yaml.safe_load(cp.read_text(encoding="utf-8"))
    caps["tools"] = [t for t in caps["tools"] if t["name"] != "show_sql"]
    cp.write_text(yaml.safe_dump(caps, allow_unicode=True), encoding="utf-8")
    assert _gateway_decision(w, "show_sql") == "allow"  # ainda no grafo
    sync(w, load_catalog(copy))
    graph = graph_of(w)
    assert capability_id("show_sql") not in {r["id"] for r in graph}
    assert not [r for r in graph if r.get("extensions", {}).get("poc.sync") and r.get("record_type") == "node"
                and r.get("node_type") == "capability" and "show_sql" in json.dumps(r)]
    assert _gateway_decision(w, "show_sql") == "deny"
    assert _gateway_decision(w, "query_metric") == "allow"


def test_world_not_initialized_exits_2(tmp_path, capsys):
    with pytest.raises(WorldNotInitialized):
        sync(tmp_path)
    assert sync_mod.main(["--world", str(tmp_path)]) == 2
    assert not (tmp_path / ".cosmos").exists()  # o sync nunca cria o World
