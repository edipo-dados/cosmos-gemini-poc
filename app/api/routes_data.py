"""Leituras sem Gemini: saúde e catálogo semântico (YAML versionado, projetado no Cosmos)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_state
from app.api.state import AppState

router = APIRouter()


@router.get("/health")
def health(state: AppState = Depends(get_state)):
    postgres, duckdb_status, etl_run_id = "ok", "ok", None
    try:
        state.audit.ping()
    except Exception:  # noqa: BLE001
        postgres = "unavailable"
    try:
        with state.engine.executor.connection() as con:
            etl_run_id = state.engine.executor.context(con, state.engine.catalog).etl_run_id
    except Exception:  # noqa: BLE001
        duckdb_status = "unavailable"
    cosmos = state.runtime.health()
    try:
        state.reader.check()
    except Exception:  # noqa: BLE001
        cosmos = "unavailable"
    ok = postgres == duckdb_status == cosmos == "ok"
    return {"status": "ok" if ok else "degraded", "gemini": "configured" if state.llm else "not_configured",
            "gemini_model": state.llm.model if state.llm else None, "postgres": postgres, "duckdb": duckdb_status,
            "cosmos": cosmos, "catalog_version": state.engine.catalog.version, "etl_run_id": etl_run_id}


@router.get("/catalog/metrics")
def catalog_metrics(state: AppState = Depends(get_state)):
    cat = state.engine.catalog
    metrics = []
    for name, m in sorted(cat.metrics.items()):
        metrics.append({
            "name": name, "business_name": m["business_name"], "description": m["description"], "formula": m["formula"],
            "source": m["source"], "denominator": m["denominator"], "status_rule": m["status_rule"],
            "time_basis": m["time_basis"], "allowed_dimensions": m["allowed_dimensions"],
            "applicable_filters": m["applicable_filters"], "owner": m["owner"], "version": m["version"],
            "tests": [{"id": t["id"], "type": t["type"]} for t in m["tests"]],
            "rules": [{"id": r["id"], "title": r["title"], "statement": r["statement"]} for r in cat.rules_for(name)]})
    return {"catalog_version": cat.version, "count": len(metrics), "metrics": metrics}


@router.get("/catalog/dimensions")
def catalog_dimensions(state: AppState = Depends(get_state)):
    cat = state.engine.catalog
    dims = [{"name": n, "business_name": d["business_name"], "type": d["type"], "description": d.get("description"),
             "allowed_for_metrics": sorted(m for m, v in cat.metrics.items() if n in v["allowed_dimensions"])}
            for n, d in sorted(cat.dimensions.items())]
    return {"catalog_version": cat.version, "count": len(dims), "dimensions": dims}


@router.get("/catalog/glossary")
def catalog_glossary(state: AppState = Depends(get_state)):
    cat = state.engine.catalog
    terms = [{"term": t["term"], "synonyms": t["synonyms"], "definition": t["definition"],
              "maps_to": [{"type": m["type"], "name": m["name"]} for m in t["maps_to"]]} for t in cat.glossary]
    return {"catalog_version": cat.version, "glossary_version": cat.glossary_version, "language": "pt-BR",
            "count": len(terms), "terms": terms}
