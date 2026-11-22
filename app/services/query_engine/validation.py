"""Validação de entrada do `query_metric`: esquema Pydantic (tipos, tamanhos) e regras de domínio (catálogo e matriz)."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from semantic.loader import Catalog

from .errors import QueryEngineError

METRIC_RE = r"^[a-z][a-z0-9_]{0,63}$"
DATE_RE = r"^\d{4}-\d{2}-\d{2}$"
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
TIME_DIMENSIONS = ("date", "month", "year")
MAX_DIMENSIONS = 3
MAX_FILTERS = 5
MAX_IN_VALUES = 50
MAX_TEXT = 64
HARD_LIMIT = 1000
DEFAULT_LIMIT = 100
Scalar = StrictStr | StrictInt


class FilterModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dimension: str = Field(pattern=METRIC_RE)
    op: Literal["eq", "in", "gte", "lte", "between"]
    value: Scalar | list[Scalar]


class OrderByModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str = Field(pattern=METRIC_RE)
    direction: Literal["asc", "desc"] = "desc"


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: str = Field(pattern=METRIC_RE)
    dimensions: list[str] = Field(default_factory=list, max_length=MAX_DIMENSIONS)
    filters: list[FilterModel] = Field(default_factory=list, max_length=MAX_FILTERS)
    date_from: str | None = Field(default=None, pattern=DATE_RE)
    date_to: str | None = Field(default=None, pattern=DATE_RE)
    order_by: OrderByModel | None = None
    limit: StrictInt = DEFAULT_LIMIT


@dataclass(frozen=True)
class ValidFilter:
    dimension: str
    op: str
    value: object  # date | int | str | list


@dataclass(frozen=True)
class ValidQuery:
    metric: str
    dimensions: list[str]
    filters: list[ValidFilter]
    date_from: date | None
    date_to: date | None
    as_of: date | None
    order_field: str | None
    order_direction: str
    limit: int
    requested: dict = field(default_factory=dict)


def parse_request(raw: dict) -> QueryRequest:
    try:
        return QueryRequest.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise QueryEngineError("invalid_arguments", f"Argumento inválido em '{where}': {first['msg']}") from exc


def _parse_date(text: str, label: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise QueryEngineError("invalid_date_range", f"{label} não é uma data válida (AAAA-MM-DD): {text}") from exc


def _check_value(dim: dict, op: str, value, domain: dict[str, set[str]]):
    """Converte e valida o valor de um filtro conforme o tipo da dimensão. Falha com invalid_filter."""
    name, typ = dim["name"], dim["type"]

    def one(v):
        if typ == "date":
            if not isinstance(v, str) or not re.match(DATE_RE, v):
                raise QueryEngineError("invalid_filter", f"Filtro '{name}': use data ISO AAAA-MM-DD.")
            try:
                return date.fromisoformat(v)
            except ValueError as exc:
                raise QueryEngineError("invalid_filter", f"Filtro '{name}': data inválida {v}.") from exc
        if typ == "month":
            if not isinstance(v, str) or not MONTH_RE.match(v):
                raise QueryEngineError("invalid_filter", f"Filtro '{name}': use o formato AAAA-MM.")
            return v
        if typ == "year":
            if not isinstance(v, int) or not 2000 <= v <= 2100:
                raise QueryEngineError("invalid_filter", f"Filtro '{name}': use ano inteiro entre 2000 e 2100.")
            return v
        if not isinstance(v, str) or not 1 <= len(v) <= MAX_TEXT:
            raise QueryEngineError("invalid_filter", f"Filtro '{name}': texto de 1 a {MAX_TEXT} caracteres.")
        if v not in domain.get(name, set()):
            raise QueryEngineError("invalid_filter", f"Filtro '{name}': valor '{v}' não existe.",
                                   {"valid_values": sorted(domain.get(name, set()))[:50]})
        return v

    categorical = typ == "categorical"
    if op in ("gte", "lte", "between") and categorical:
        raise QueryEngineError("invalid_filter", f"Filtro '{name}': dimensão categórica aceita só eq e in.")
    if op in ("eq", "gte", "lte"):
        if isinstance(value, list):
            raise QueryEngineError("invalid_filter", f"Filtro '{name}': o operador {op} exige um valor único.")
        return one(value)
    if not isinstance(value, list):
        raise QueryEngineError("invalid_filter", f"Filtro '{name}': o operador {op} exige uma lista.")
    if op == "between":
        if len(value) != 2:
            raise QueryEngineError("invalid_filter", f"Filtro '{name}': between exige 2 valores.")
        lo, hi = one(value[0]), one(value[1])
        if lo > hi:
            raise QueryEngineError("invalid_filter", f"Filtro '{name}': between com início maior que o fim.")
        return [lo, hi]
    if not 1 <= len(value) <= MAX_IN_VALUES:
        raise QueryEngineError("invalid_filter", f"Filtro '{name}': in aceita de 1 a {MAX_IN_VALUES} valores.")
    return [one(v) for v in value]


def validate(req: QueryRequest, catalog: Catalog, domain: dict[str, set[str]], data_range: tuple[date, date],
             default_as_of: date) -> ValidQuery:
    metric = catalog.metrics.get(req.metric)
    if metric is None:
        close = difflib.get_close_matches(req.metric, list(catalog.metrics), n=3, cutoff=0.5)
        raise QueryEngineError("unknown_metric", f"Métrica '{req.metric}' não existe no catálogo.",
                               {"available_metrics": sorted(catalog.metrics), "suggestions": close})
    allowed = metric["allowed_dimensions"]
    dims = req.dimensions
    if len(set(dims)) != len(dims):
        raise QueryEngineError("invalid_dimension_combination", "Dimensões repetidas.")
    for d in dims:
        if d not in allowed:
            raise QueryEngineError("dimension_not_allowed",
                                   f"A dimensão '{d}' não é permitida para a métrica '{metric['name']}'.",
                                   {"allowed_dimensions": allowed})
    if sum(d in TIME_DIMENSIONS for d in dims) > 1:
        raise QueryEngineError("invalid_dimension_combination", "Use no máximo uma dimensão de tempo (date, month ou year).")
    for d in metric.get("required_dimensions", []):
        if d not in dims:
            raise QueryEngineError("missing_required_dimension", f"A métrica '{metric['name']}' exige a dimensão '{d}'.")

    filters: list[ValidFilter] = []
    for f in req.filters:
        if f.dimension not in catalog.dimensions:
            raise QueryEngineError("invalid_filter", f"Dimensão de filtro '{f.dimension}' não existe.",
                                   {"allowed_filters": metric["applicable_filters"]["dimensions"]})
        if f.dimension not in metric["applicable_filters"]["dimensions"]:
            raise QueryEngineError("invalid_filter",
                                   f"Filtro por '{f.dimension}' não é aplicável à métrica '{metric['name']}'.",
                                   {"allowed_filters": metric["applicable_filters"]["dimensions"]})
        filters.append(ValidFilter(f.dimension, f.op, _check_value(catalog.dimensions[f.dimension], f.op, f.value, domain)))

    date_from = _parse_date(req.date_from, "date_from") if req.date_from else None
    date_to = _parse_date(req.date_to, "date_to") if req.date_to else None
    lo, hi = data_range
    if date_from and not metric["applicable_filters"]["date_range"]:
        raise QueryEngineError("invalid_date_range",
                               f"A métrica '{metric['name']}' usa janela fixa: date_from não é aceito (use date_to como data de referência).")
    for label, v in (("date_from", date_from), ("date_to", date_to)):
        if v and not lo <= v <= hi:
            raise QueryEngineError("invalid_date_range", f"{label} {v} fora do intervalo dos dados ({lo} a {hi}).")
    if date_from and date_to and date_from > date_to:
        raise QueryEngineError("invalid_date_range", "date_from é maior que date_to.")

    as_of = None
    if metric.get("window"):
        as_of = date_to or min(default_as_of, hi)

    order_field = None
    direction = "desc"
    if req.order_by:
        if req.order_by.field not in ("metric", *dims):
            raise QueryEngineError("invalid_order", "order_by deve ser 'metric' ou uma das dimensões pedidas.",
                                   {"valid_fields": ["metric", *dims]})
        order_field = "value" if req.order_by.field == "metric" else req.order_by.field
        direction = req.order_by.direction
    if not 1 <= req.limit <= HARD_LIMIT:
        raise QueryEngineError("invalid_limit", f"limit deve ficar entre 1 e {HARD_LIMIT}.")
    return ValidQuery(metric=metric["name"], dimensions=list(dims), filters=filters, date_from=date_from, date_to=date_to,
                      as_of=as_of, order_field=order_field, order_direction=direction, limit=req.limit,
                      requested=req.model_dump(mode="json"))
