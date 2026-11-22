"""Leitura do conhecimento semântico guardado no grafo do Cosmos (`.cosmos/graph.json`).

Lê por caminho explícito e não usa `load_graph` do Cosmos, que engole qualquer erro e devolve lista vazia
(docs/ARCHITECTURE.md, seção 5.5). Cache por mtime. `explain_metric` usa `tool_explain` do servidor MCP do Cosmos.
"""
from __future__ import annotations

import json
import threading
import unicodedata
from pathlib import Path

from tools import cosmos_mcp_server as mcp

from semantic.sync_to_cosmos import metric_id

from .errors import SemanticCatalogUnavailable, ToolError

MAX_RESULTS = 10


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c)).strip()


class SemanticReader:
    def __init__(self, graph_path: Path | str):
        self.path = Path(graph_path)
        self._lock = threading.Lock()
        self._cache: tuple[int, list[dict]] | None = None

    # ---- grafo ----
    def graph(self) -> list[dict]:
        try:
            mtime = self.path.stat().st_mtime_ns
            with self._lock:
                if self._cache and self._cache[0] == mtime:
                    return self._cache[1]
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SemanticCatalogUnavailable(f"Grafo semântico do Cosmos ilegível ({type(exc).__name__}).") from exc
        if not isinstance(data, list) or not any(isinstance(r, dict) and r.get("entity_type") == "poc.metric" for r in data):
            raise SemanticCatalogUnavailable("O grafo semântico do Cosmos não tem nós poc.metric. Rode o sync.")
        with self._lock:
            self._cache = (mtime, data)
        return data

    def _entities(self, entity_type: str) -> list[dict]:
        return [r for r in self.graph() if r.get("entity_type") == entity_type]

    def check(self) -> int:
        """Usado no início da API: devolve a quantidade de métricas ou levanta semantic_catalog_unavailable."""
        return len(self._entities("poc.metric"))

    # ---- ferramentas ----
    def list_metrics(self) -> list[dict]:
        out = []
        for n in sorted(self._entities("poc.metric"), key=lambda r: r["display_name"]):
            e = n["extensions"]["poc.metric"]
            out.append({"name": n["display_name"], "business_name": e["business_name"], "description": e["description"],
                        "value_type": e["value_type"], "version": e["version"], "owner": e["owner"],
                        "allowed_dimensions": e["allowed_dimensions"]})
        return out

    def list_dimensions(self, metric: str | None = None) -> list[dict]:
        out = []
        for n in sorted(self._entities("poc.dimension"), key=lambda r: r["display_name"]):
            e = n["extensions"]["poc.dimension"]
            if metric is not None and metric not in e["allowed_for_metrics"]:
                continue
            out.append({"name": n["display_name"], "business_name": e["business_name"], "type": e["type"],
                        "description": e["description"], "allowed_for_metrics": e["allowed_for_metrics"]})
        return out

    def glossary(self) -> list[dict]:
        out = []
        for n in sorted(self._entities("poc.glossary_term"), key=lambda r: r["display_name"]):
            e = n["extensions"]["poc.glossary_term"]
            out.append({"term": n["display_name"], "synonyms": n.get("aliases", []), "definition": n["description"],
                        "maps_to": [{"type": m["type"], "name": m["name"]} for m in e["maps_to"]]})
        return out

    def search(self, query: str) -> list[dict]:
        """Comparação sem acento e sem caixa com nome, aliases e descrição (o `cosmos_query` do Cosmos não filtra aliases)."""
        q = normalize(query)
        hits: list[tuple[int, dict]] = []
        for etype, kind in (("poc.glossary_term", "glossary_term"), ("poc.metric", "metric"), ("poc.dimension", "dimension")):
            for n in self._entities(etype):
                ext = n["extensions"].get(etype, {})
                labels = [n["display_name"], *n.get("aliases", [])]
                matched, score = None, 0
                for label in labels:
                    lab = normalize(label)
                    if lab and (lab in q or q in lab):
                        if len(lab) > score:
                            matched, score = label, len(lab)
                if matched is None and q and q in normalize(n.get("description", "")):
                    matched, score = "(descrição)", 1
                if matched is None:
                    continue
                item = {"type": kind, "name": n["display_name"], "business_name": ext.get("business_name", n["display_name"]),
                        "matched_alias": matched, "description": n.get("description", "")}
                if kind == "glossary_term":
                    item["maps_to"] = [m["name"] for m in ext["maps_to"]]
                hits.append((score, item))
        hits.sort(key=lambda h: -h[0])
        return [h[1] for h in hits[:MAX_RESULTS]]

    def explain(self, metric: str) -> dict:
        graph = self.graph()
        res = mcp.tool_explain(graph, {"id": metric_id(metric)})
        if "error" in res:  # tool_explain devolve o erro como retorno normal; vira internal_error
            raise ToolError("internal_error", f"Métrica '{metric}' ausente do grafo do Cosmos (divergência entre YAML e grafo).")
        ext = res["node"]["extensions"]["poc.metric"]
        rules = [{"title": n.get("display_name"), "statement": n.get("statement")}
                 for n in res["neighbours"] if n.get("knowledge_class") == "rule"]
        return {"metric": metric, "business_name": ext["business_name"], "description": ext["description"],
                "formula": ext["formula"], "denominator": ext["denominator"], "status_rule": ext["status_rule"],
                "time_basis": ext["time_basis"], "base_filter": ext["base_filter"],
                "allowed_dimensions": ext["allowed_dimensions"], "applicable_filters": ext["applicable_filters"],
                "owner": ext["owner"], "version": ext["version"], "source": ext["source"],
                "rules": sorted(rules, key=lambda r: r["title"] or ""),
                "cosmos_node_id": res["node"]["id"]}
