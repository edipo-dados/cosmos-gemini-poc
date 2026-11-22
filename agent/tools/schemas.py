"""Argumentos das 7 ferramentas do agente. Falha de esquema (tipo, campo extra, tamanho, formato) é sempre `invalid_arguments`.
O esquema é validado antes do gateway do Cosmos (docs/ARCHITECTURE.md, seção 5.3, passo 1)."""
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from app.services.query_engine.validation import METRIC_RE, QueryRequest

TOOL_NAMES = ("search_concepts", "explain_metric", "list_metrics", "list_dimensions", "query_metric", "show_sql",
              "get_evidence")


class SearchConceptsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: StrictStr = Field(min_length=1, max_length=200)


class ExplainMetricArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: StrictStr = Field(pattern=METRIC_RE)


class ListMetricsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListDimensionsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: StrictStr | None = Field(default=None, pattern=METRIC_RE)


class QueryIdArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_id: UUID


ARG_MODELS: dict[str, type[BaseModel]] = {
    "search_concepts": SearchConceptsArgs,
    "explain_metric": ExplainMetricArgs,
    "list_metrics": ListMetricsArgs,
    "list_dimensions": ListDimensionsArgs,
    "query_metric": QueryRequest,
    "show_sql": QueryIdArgs,
    "get_evidence": QueryIdArgs,
}

# código de erro de ferramenta -> status HTTP (docs/ARCHITECTURE.md, seção 6.1)
HTTP_STATUS = {
    "invalid_arguments": 400, "invalid_user_id": 400, "invalid_question": 400, "invalid_session_id": 400,
    "unknown_tool": 404,
    "unknown_metric": 422, "dimension_not_allowed": 422, "invalid_dimension_combination": 422,
    "missing_required_dimension": 422, "invalid_filter": 422, "invalid_date_range": 422, "invalid_order": 422,
    "invalid_limit": 422,
    "tool_not_authorized": 403,
    "query_not_found": 404,
    "no_sql_available": 409,
    "query_timeout": 504,
    "audit_failed": 500, "internal_error": 500,
    "cosmos_runtime_unavailable": 503, "semantic_catalog_unavailable": 503,
}
