"""Sincroniza o catálogo semântico versionado (YAML) com o World do Cosmos.

Mecanismo usado (PROVEN, ver docs/COSMOS_DISCOVERY.md 5.6 e 5.10): escrita de registros no `.cosmos/graph.json`,
validados por `tools.validate_ontology.validate_graph` do próprio Cosmos antes da gravação.
NÃO usa o fluxo oficial de admissão de conhecimento (Candidate Intake, DOCUMENTED-ONLY): grava conhecimento já `active`.

Relação com o catálogo: o YAML em `semantic/` é a fonte de verdade. O Cosmos recebe uma projeção. Todo registro gerado
leva `extensions["poc.sync"].owner == "semantic-sync"`; a cada execução esses registros são removidos e regravados a partir do
YAML, então o que sai do YAML sai do grafo. Registros do `cosmos init` (sem o marcador) ficam intactos.

Uso: python -m semantic.sync_to_cosmos [--world DIR]. Sai com 2 e `world_not_initialized` se o World não existir.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
try:  # o pacote do Cosmos é instalado em modo editável; o caminho do clone é só fallback
    from tools.reference_repository_projection import stable_cosmos_ref
    from tools.validate_ontology import validate_graph
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(ROOT / ".vendor" / "cosmos"))
    from tools.reference_repository_projection import stable_cosmos_ref
    from tools.validate_ontology import validate_graph

from semantic.loader import Catalog, load_catalog

log = logging.getLogger("poc.sync")
OWNER = "semantic-sync"
CATALOG_SYSTEM = "poc-semantic-catalog"
TOOL_SYSTEM_DEFAULT = "poc-tools"
METRIC_EXT_KEYS = ("business_name", "description", "formula", "source", "value_type", "denominator", "status_rule",
                   "time_basis", "base_filter", "window", "required_dimensions", "allowed_dimensions",
                   "applicable_filters", "owner", "version", "tests")


class WorldNotInitialized(RuntimeError):
    """O World (cosmos.environment.json e .cosmos/graph.json) não existe. Quem cria é `cosmos init`."""


# IDs: stable_cosmos_ref(chave semântica) é determinístico, então reexecutar não duplica.
def metric_id(name: str) -> str: return stable_cosmos_ref(f"metric:{name}")
def dimension_id(name: str) -> str: return stable_cosmos_ref(f"dimension:{name}")
def glossary_id(term: str) -> str: return stable_cosmos_ref(f"glossary:{term}")
def rule_id(rid: str) -> str: return stable_cosmos_ref(f"rule:{rid}")
def capability_id(tool: str) -> str: return stable_cosmos_ref(f"cap:tool:{tool}")
def actor_id(name: str) -> str: return stable_cosmos_ref(f"actor:{name}")
def edge_id(metric: str, rid: str) -> str: return stable_cosmos_ref(f"edge:{metric}:governed_by:{rid}")


def _locator(uri: str, version: str, display: str) -> dict:
    return {"system": CATALOG_SYSTEM, "uri": uri, "revision": version, "display": display}


def _build(catalog: Catalog, creator_ref: str) -> list[dict]:
    ver = catalog.version
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def common(rid: str, uri: str, display: str) -> dict:
        loc = _locator(uri, ver, display)
        return {"record_type": "node", "id": rid, "authority": {"class": "external", "source": loc},
                "provenance": [{"relation": "created_by", "source": creator_ref},
                               {"relation": "imported_from", "source": loc}],
                "temporal": {"created_at": now}}

    def sync_ext(uri: str, extra: dict | None = None) -> dict:
        return {"poc.sync": {"owner": OWNER, "catalog_version": ver, "source_uri": uri}, **(extra or {})}

    out: list[dict] = []
    caps = catalog.capabilities
    agent = {**common(actor_id(caps["grantee"]), "semantic/rules/agent_capabilities.yaml", "agente"),
             "node_type": "actor", "schema": "cosmos.actor/1", "actor_type": "service", "display_name": caps["grantee"],
             "implementation": "poc-gemini-orchestrator", "extensions": sync_ext("semantic/rules/agent_capabilities.yaml")}
    user = {**common(actor_id(caps["requester"]), "semantic/rules/agent_capabilities.yaml", "usuário"),
            "node_type": "actor", "schema": "cosmos.actor/1", "actor_type": "human", "display_name": caps["requester"],
            "extensions": sync_ext("semantic/rules/agent_capabilities.yaml")}
    out += [agent, user]

    for name, d in catalog.dimensions.items():
        uri = f"semantic/dimensions/{name}.yaml"
        allowed = sorted(m for m, md in catalog.metrics.items() if name in md["allowed_dimensions"])
        out.append({**common(dimension_id(name), uri, d["business_name"]), "node_type": "entity", "schema": "cosmos.node/1",
                    "entity_type": "poc.dimension", "display_name": name, "summary": d["business_name"],
                    "description": d["description"], "aliases": [d["business_name"]],
                    "extensions": sync_ext(uri, {"poc.dimension": {"business_name": d["business_name"], "type": d["type"],
                                                                   "description": d["description"], "allowed_for_metrics": allowed}})})
    for name, m in catalog.metrics.items():
        uri = f"semantic/metrics/{name}.yaml"
        out.append({**common(metric_id(name), uri, m["business_name"]), "node_type": "entity", "schema": "cosmos.node/1",
                    "entity_type": "poc.metric", "display_name": name, "summary": m["business_name"],
                    "description": m["description"], "aliases": [m["business_name"]],
                    "extensions": sync_ext(uri, {"poc.metric": {k: m[k] for k in METRIC_EXT_KEYS if k in m}})})
    for t in catalog.glossary:
        uri = "semantic/glossary/glossary.yaml"
        pool = {"metric": metric_id, "dimension": dimension_id}
        maps = [{"type": r["type"], "name": r["name"], "ref": pool[r["type"]](r["name"])} for r in t["maps_to"]]
        out.append({**common(glossary_id(t["term"]), uri, t["term"]), "node_type": "entity", "schema": "cosmos.node/1",
                    "entity_type": "poc.glossary_term", "display_name": t["term"], "description": t["definition"],
                    "aliases": list(t["synonyms"]),
                    "extensions": sync_ext(uri, {"poc.glossary_term": {"language": "pt-BR", "maps_to": maps,
                                                                       "glossary_version": catalog.glossary_version}})})
    metric_ids = {n: metric_id(n) for n in catalog.metrics}
    for r in catalog.rules:
        uri = "semantic/rules/business_rules.yaml"
        targets = list(catalog.metrics) if r["applies_to"] == "all" else r["applies_to"]
        out.append({**common(rule_id(r["id"]), uri, r["title"]), "node_type": "knowledge", "schema": "cosmos.knowledge/1",
                    "knowledge_class": "rule", "lifecycle_state": "active", "display_name": r["title"],
                    "statement": r["statement"], "scope_refs": [metric_ids[m] for m in targets],
                    "extensions": sync_ext(uri, {"poc.rule": {"id": r["id"], "category": r["category"],
                                                              "applies_to": targets, "rules_version": catalog.rules_version}})})
        for m in targets:
            loc = _locator(uri, ver, r["title"])
            out.append({"record_type": "edge", "schema": "cosmos.edge/1", "id": edge_id(m, r["id"]),
                        "authority": {"class": "external", "source": loc},
                        "provenance": [{"relation": "created_by", "source": creator_ref}, {"relation": "imported_from", "source": loc}],
                        "temporal": {"created_at": now}, "relation_type": "core.governed_by",
                        "source": metric_ids[m], "target": rule_id(r["id"]), "extensions": sync_ext(uri)})
    for tool in caps["tools"]:
        uri = "semantic/rules/agent_capabilities.yaml"
        out.append({**common(capability_id(tool["name"]), uri, tool["name"]), "node_type": "capability",
                    "schema": "cosmos.capability/1", "action": "tool.invoke", "decision": "allow",
                    "grantee_refs": [agent["id"]], "resources": [{"system": caps["system"], "uri": f"tool:{tool['name']}"}],
                    "display_name": f"tool.invoke {tool['name']}",
                    "extensions": sync_ext(uri, {"poc.tool": {"name": tool["name"], "description": tool["description"]}})})
    return out


def _is_owned(rec: dict) -> bool:
    return (rec.get("extensions") or {}).get("poc.sync", {}).get("owner") == OWNER


def _content(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if k != "temporal"}


def _merge_temporal(new: list[dict], old_owned: dict[str, dict]) -> int:
    """Preserva `created_at` de registros já existentes e só marca `updated_at` quando o conteúdo mudou.
    Sem isso, duas execuções seguidas gerariam grafos diferentes só pelo relógio."""
    changed = 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for rec in new:
        old = old_owned.get(rec["id"])
        if old is None:
            changed += 1
        elif _content(old) == _content(rec):
            rec["temporal"] = old["temporal"]
        else:
            rec["temporal"] = {"created_at": old["temporal"]["created_at"], "updated_at": now}
            changed += 1
    changed += len(set(old_owned) - {r["id"] for r in new})
    return changed


def sync(world_dir: Path | str, catalog: Catalog | None = None) -> dict:
    world = Path(world_dir)
    env = world / "cosmos.environment.json"
    graph_path = world / ".cosmos" / "graph.json"
    if not env.is_file() or not graph_path.is_file():
        raise WorldNotInitialized(f"world_not_initialized: execute `cosmos init` em {world}")
    catalog = catalog or load_catalog()
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    old_owned = {r["id"]: r for r in graph if _is_owned(r)}
    owned_ids = set(old_owned)
    foreign = [r for r in graph if r["id"] not in owned_ids
               and not (r.get("record_type") == "edge" and (r.get("source") in owned_ids or r.get("target") in owned_ids))]
    creator = next((r["id"] for r in foreign if r.get("node_type") == "actor"), actor_id(catalog.capabilities["grantee"]))
    new = _build(catalog, creator)
    changed = _merge_temporal(new, old_owned)
    result = foreign + new
    errors = validate_graph(result)
    if errors:
        raise ValueError(f"validate_graph rejeitou o grafo gerado: {errors[:3]}")
    tmp = graph_path.with_name(graph_path.name + ".tmp")
    if changed or [r["id"] for r in result] != [r["id"] for r in graph]:
        tmp.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, graph_path)
        wrote = True
    else:
        wrote = False
    kinds: dict[str, int] = {}
    for r in new:
        k = r.get("entity_type") or r.get("knowledge_class") or r.get("node_type") or r["record_type"]
        kinds[k] = kinds.get(k, 0) + 1
    return {"world": str(world), "catalog_version": catalog.version, "written": wrote, "changed_records": changed,
            "removed_stale": len(set(old_owned) - {r["id"] for r in new}), "records_generated": len(new),
            "by_kind": kinds, "preserved_foreign_records": len(foreign), "validate_graph_errors": errors}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--world", default=None, help="diretório do World (padrão: COSMOS_WORLD_DIR ou raiz do projeto)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    world = args.world or os.environ.get("COSMOS_WORLD_DIR") or "."
    world_path = Path(world) if Path(world).is_absolute() else ROOT / world
    try:
        summary = sync(world_path)
    except WorldNotInitialized as exc:
        log.error("%s", exc)
        print("world_not_initialized", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
