"""Construção dos serviços da API e verificação dos pré-requisitos (falha em qualquer item impede a API de subir)."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from google.genai import types

from agent.gemini.client import GeminiClient, LLMClient
from agent.gemini.errors import GeminiNotConfigured
from agent.orchestration.loop import ChatOrchestrator
from agent.tools.cosmos_gateway import CosmosRuntime
from agent.tools.executor import ToolExecutor
from agent.tools.semantic_reader import SemanticReader
from app.config import Settings
from app.db import make_engine
from app.services.audit import AuditStore
from app.services.query_engine import QueryEngine
from semantic.loader import load_catalog

log = logging.getLogger("poc.api")


@dataclass
class AppState:
    settings: Settings
    runtime: CosmosRuntime
    reader: SemanticReader
    engine: QueryEngine
    audit: AuditStore
    executor: ToolExecutor
    llm: LLMClient | None
    chat: ChatOrchestrator | None


def build_state(settings: Settings, http_options: types.HttpOptions | None = None, llm: LLMClient | None = None) -> AppState:
    catalog = load_catalog()
    runtime = CosmosRuntime(settings.resolve(settings.cosmos_world_dir))
    reader = SemanticReader(runtime.graph_path)
    reader.check()  # semantic_catalog_unavailable impede a subida
    engine = QueryEngine(settings.duckdb_file, settings.data_end_date, catalog)
    with engine.executor.connection() as con:  # DuckDB existente e com etl_meta
        engine.executor.context(con, catalog)
    audit = AuditStore(make_engine("app", settings))
    audit.ping()
    executor = ToolExecutor(runtime, reader, engine, audit)
    if llm is None:
        try:
            llm = GeminiClient(settings.gemini_api_key.get_secret_value(), settings.gemini_model, http_options)
        except GeminiNotConfigured as exc:
            log.warning("Gemini não configurado: %s", exc.message)
    chat = ChatOrchestrator(llm, executor, runtime, audit) if llm else None
    return AppState(settings, runtime, reader, engine, audit, executor, llm, chat)
