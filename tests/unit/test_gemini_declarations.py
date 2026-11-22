"""Declarações e configuração com os tipos reais do SDK google-genai. Estes testes NÃO verificam o Gemini."""
from __future__ import annotations

import yaml
from google.genai import types

from agent.gemini.client import GeminiClient, build_config
from agent.gemini.declarations import build_declarations
from agent.gemini.prompts import SYSTEM_INSTRUCTION
from agent.tools.schemas import TOOL_NAMES
from semantic.loader import SEMANTIC_DIR
from support.fake_gemini import ScriptedGemini, text


def test_exactly_the_seven_registered_tools():
    decls = build_declarations()
    assert all(isinstance(d, types.FunctionDeclaration) for d in decls)
    names = [d.name for d in decls]
    caps = yaml.safe_load((SEMANTIC_DIR / "rules" / "agent_capabilities.yaml").read_text(encoding="utf-8"))
    assert names == list(TOOL_NAMES)
    assert set(names) == {t["name"] for t in caps["tools"]}
    assert not {"cosmos_open", "cosmos_act", "execute_sql", "run_sql"} & set(names)


def test_no_declaration_accepts_sql_or_table_names():
    decls = {d.name: d for d in build_declarations()}
    qm = decls["query_metric"].parameters
    assert set(qm.properties) == {"metric", "dimensions", "filters", "date_from", "date_to", "order_by", "limit"}
    assert qm.required == ["metric"]
    assert qm.properties["filters"].items.properties["op"].enum == ["eq", "in", "gte", "lte", "between"]
    for d in decls.values():
        props = set(d.parameters.properties) if d.parameters else set()
        assert not {"sql", "query_sql", "table", "tables"} & props


def test_config_disables_automatic_function_calling():
    cfg = build_config()
    assert isinstance(cfg, types.GenerateContentConfig)
    assert cfg.automatic_function_calling.disable is True
    assert cfg.temperature == 0
    assert cfg.system_instruction == SYSTEM_INSTRUCTION
    assert [d.name for d in cfg.tools[0].function_declarations] == list(TOOL_NAMES)


def test_sdk_serializes_declarations_on_the_wire():
    """O SDK real serializa a requisição; o transporte falso só captura o corpo HTTP."""
    fake = ScriptedGemini().load(text("ok"))
    client = GeminiClient("chave-falsa-de-teste", "modelo-x", fake.http_options())
    resp = client.generate([types.Content(role="user", parts=[types.Part.from_text(text="Qual o faturamento?")])])
    assert resp.text == "ok"
    body = fake.requests[0]
    assert fake.urls[0].endswith("/models/modelo-x:generateContent")
    assert fake.api_keys[0] == "chave-falsa-de-teste"
    sent = [f["name"] for f in body["tools"][0]["functionDeclarations"]]
    assert sent == list(TOOL_NAMES)
    assert body["generationConfig"]["temperature"] == 0
    assert "português" in body["systemInstruction"]["parts"][0]["text"]
    assert body["toolConfig"]["functionCallingConfig"]["mode"] == "AUTO"


def test_system_instruction_rules():
    s = SYSTEM_INSTRUCTION
    for needle in ("português", "NÃO escreve SQL", "query_id", "explain_metric", "Nunca invente"):
        assert needle in s
