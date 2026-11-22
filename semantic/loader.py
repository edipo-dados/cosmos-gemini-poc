"""Carrega e valida o catálogo semântico versionado (YAML). Fonte de verdade do projeto.

O Query Engine e o sync para o Cosmos leem este catálogo. O Cosmos recebe uma projeção (ver sync_to_cosmos.py).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import jsonschema
import yaml

SEMANTIC_DIR = Path(__file__).resolve().parent
ROOT = SEMANTIC_DIR.parent
REFERENCE_PREFIX = "pipelines/quality/reference_sql/"


class CatalogError(ValueError):
    """Catálogo inválido (esquema ou consistência)."""


@dataclass(frozen=True)
class Catalog:
    metrics: dict[str, dict]
    dimensions: dict[str, dict]
    rules: list[dict]
    rules_version: str
    glossary: list[dict]
    glossary_version: str
    capabilities: dict
    sources: dict
    version: str
    root: Path

    def rules_for(self, metric: str) -> list[dict]:
        return [r for r in self.rules if r["applies_to"] == "all" or metric in r["applies_to"]]


def _yaml(path: Path):
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _schema(name: str) -> dict:
    return json.loads((SEMANTIC_DIR / "schema" / f"{name}.schema.json").read_text(encoding="utf-8"))


def _validate(instance, schema_name: str, origin: Path) -> None:
    try:
        jsonschema.validate(instance, _schema(schema_name))
    except jsonschema.ValidationError as exc:
        where = "/".join(str(p) for p in exc.absolute_path)
        raise CatalogError(f"{origin.name}: {exc.message} (em {where or 'raiz'})") from exc


def _check_consistency(c: Catalog) -> None:
    joins = c.sources["joins"]
    for name, j in joins.items():
        for req in j["requires"]:
            if req not in joins:
                raise CatalogError(f"sources.yaml: junção '{name}' exige '{req}' inexistente")
    for d in c.dimensions.values():
        if d["type"] == "categorical" and "domain" not in d:
            raise CatalogError(f"dimensão {d['name']}: categórica exige domain")
        for j in d["requires_joins"]:
            if j not in joins:
                raise CatalogError(f"dimensão {d['name']}: junção '{j}' inexistente")
    for m in c.metrics.values():
        n = m["name"]
        for d in m["allowed_dimensions"]:
            if d not in c.dimensions:
                raise CatalogError(f"métrica {n}: dimensão '{d}' inexistente")
        if set(m["applicable_filters"]["dimensions"]) - set(m["allowed_dimensions"]):
            raise CatalogError(f"métrica {n}: filtros fora das dimensões permitidas")
        if set(m.get("required_dimensions", [])) - set(m["allowed_dimensions"]):
            raise CatalogError(f"métrica {n}: dimensão obrigatória não permitida")
        for j in m["joins"]:
            if j not in joins:
                raise CatalogError(f"métrica {n}: junção '{j}' inexistente")
        if m["grain"] not in c.sources["grains"] and m["grain"] != "growth":
            raise CatalogError(f"métrica {n}: grão '{m['grain']}' inexistente")
        if m.get("kind") == "growth" and m.get("base_metric") not in c.metrics:
            raise CatalogError(f"métrica {n}: base_metric inexistente")
        for t in m["tests"]:
            if t["type"] == "reconciliation":
                ref = t.get("reference_sql", "")
                if not ref.startswith(REFERENCE_PREFIX) or not (c.root / ref).is_file():
                    raise CatalogError(f"métrica {n}, teste {t['id']}: reference_sql inexistente ({ref})")
            elif t.get("other_metric") and t["other_metric"] not in c.metrics:
                raise CatalogError(f"métrica {n}, teste {t['id']}: other_metric inexistente")
    ids = [r["id"] for r in c.rules]
    if len(ids) != len(set(ids)):
        raise CatalogError("regras com id duplicado")
    for r in c.rules:
        if r["applies_to"] != "all":
            for m in r["applies_to"]:
                if m not in c.metrics:
                    raise CatalogError(f"regra {r['id']}: métrica '{m}' inexistente")
    for t in c.glossary:
        for ref in t["maps_to"]:
            pool = c.metrics if ref["type"] == "metric" else c.dimensions
            if ref["name"] not in pool:
                raise CatalogError(f"glossário '{t['term']}': {ref['type']} '{ref['name']}' inexistente")
    for tool in c.capabilities["tools"]:
        if not tool["name"]:
            raise CatalogError("ferramenta sem nome")


def _compute_version(parts: dict) -> str:
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def load_catalog(semantic_dir: Path | None = None, root: Path | None = None) -> Catalog:
    """Lê todos os YAML, valida pelos esquemas JSON e pela consistência cruzada. `catalog_version` é um hash do conteúdo."""
    base = Path(semantic_dir) if semantic_dir else SEMANTIC_DIR
    root = Path(root) if root else ROOT
    sources = _yaml(base / "sources.yaml")
    _validate(sources, "sources", base / "sources.yaml")
    metrics: dict[str, dict] = {}
    for p in sorted((base / "metrics").glob("*.yaml")):
        m = _yaml(p)
        _validate(m, "metric", p)
        if m["name"] != p.stem:
            raise CatalogError(f"{p.name}: o nome do arquivo deve ser {m['name']}.yaml")
        metrics[m["name"]] = m
    dimensions: dict[str, dict] = {}
    for p in sorted((base / "dimensions").glob("*.yaml")):
        d = _yaml(p)
        _validate(d, "dimension", p)
        if d["name"] != p.stem:
            raise CatalogError(f"{p.name}: o nome do arquivo deve ser {d['name']}.yaml")
        dimensions[d["name"]] = d
    rules_doc = _yaml(base / "rules" / "business_rules.yaml")
    _validate(rules_doc, "rules", base / "rules" / "business_rules.yaml")
    glossary_doc = _yaml(base / "glossary" / "glossary.yaml")
    _validate(glossary_doc, "glossary", base / "glossary" / "glossary.yaml")
    caps = _yaml(base / "rules" / "agent_capabilities.yaml")
    _validate(caps, "capabilities", base / "rules" / "agent_capabilities.yaml")
    version = _compute_version({"sources": sources, "metrics": metrics, "dimensions": dimensions,
                                "rules": rules_doc, "glossary": glossary_doc, "capabilities": caps})
    catalog = Catalog(metrics=metrics, dimensions=dimensions, rules=rules_doc["rules"], rules_version=rules_doc["version"],
                      glossary=glossary_doc["terms"], glossary_version=glossary_doc["version"], capabilities=caps,
                      sources=sources, version=version, root=root)
    _check_consistency(catalog)
    return catalog
