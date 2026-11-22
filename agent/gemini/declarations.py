"""Declarações das 7 ferramentas com os tipos reais do SDK `google-genai`, geradas a partir dos modelos Pydantic.
As ferramentas `cosmos_open` e `cosmos_act` do MCP do Cosmos NÃO são expostas (docs/ARCHITECTURE.md, seção 4)."""
from __future__ import annotations

from google.genai import types

from agent.tools.schemas import ARG_MODELS, TOOL_NAMES

DESCRIPTIONS = {
    "search_concepts": "Busca métricas, dimensões e termos do glossário de negócio (inclusive sinônimos em português) por texto. Use para descobrir o nome técnico da métrica.",
    "explain_metric": "Explica uma métrica cadastrada: fórmula, denominador, filtros, regras de status, dimensões permitidas, responsável e versão.",
    "list_metrics": "Lista as métricas cadastradas, o intervalo de datas dos dados (data_range) e a data de referência (data_as_of).",
    "list_dimensions": "Lista as dimensões de análise. Com 'metric', devolve só as permitidas para essa métrica.",
    "query_metric": "Consulta uma métrica cadastrada no Query Engine (somente leitura). Devolve linhas, filtros aplicados e query_id. Não aceita SQL.",
    "show_sql": "Mostra o SQL parametrizado executado por uma consulta anterior, pelo query_id.",
    "get_evidence": "Devolve as evidências de uma consulta anterior pelo query_id: regras, filtros, versão do catálogo, execução do ETL e referências do Cosmos.",
}
FIELD_HELP = {
    "query": "Texto livre, por exemplo 'faturamento' ou 'ticket médio'.",
    "metric": "Nome técnico da métrica (ex.: net_revenue).",
    "dimensions": "Dimensões de agrupamento permitidas para a métrica (ex.: region, month, category). Máximo 3.",
    "filters": "Filtros {dimension, op, value}; op em eq, in, gte, lte, between. Valores categóricos devem existir nos dados.",
    "date_from": "Início do período (AAAA-MM-DD).",
    "date_to": "Fim do período (AAAA-MM-DD). Para active_customers é a data de referência.",
    "order_by": "Ordenação {field: 'metric' ou uma das dimensões pedidas, direction: asc|desc}.",
    "limit": "Máximo de linhas (1 a 1000, padrão 100).",
    "query_id": "query_id devolvido por query_metric.",
}


def _clean(node):
    """Remove `title` (ruído do Pydantic) e acrescenta descrição aos campos conhecidos."""
    if isinstance(node, dict):
        out = {k: _clean(v) for k, v in node.items() if k != "title"}
        props = out.get("properties")
        if isinstance(props, dict):
            for name, spec in props.items():
                if isinstance(spec, dict) and name in FIELD_HELP and name != "field":
                    spec.setdefault("description", FIELD_HELP[name])
        return out
    if isinstance(node, list):
        return [_clean(v) for v in node]
    return node


def build_declarations() -> list[types.FunctionDeclaration]:
    decls = []
    for name in TOOL_NAMES:
        schema = _clean(ARG_MODELS[name].model_json_schema())
        schema.pop("additionalProperties", None)  # o subconjunto de Schema da API não usa
        parameters = None
        if schema.get("properties"):
            parameters = types.Schema.from_json_schema(json_schema=types.JSONSchema(**schema))
        decls.append(types.FunctionDeclaration(name=name, description=DESCRIPTIONS[name], parameters=parameters))
    return decls


def build_tools() -> list[types.Tool]:
    return [types.Tool(function_declarations=build_declarations())]
