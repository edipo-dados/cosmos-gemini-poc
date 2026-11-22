"""Sobe a API real (uvicorn) com o SDK google-genai real e um transporte HTTP roteirizado no lugar do Gemini.
Serve para exercitar o loop de Function Calling por HTTP de verdade sem chave. NÃO é o Gemini e não verifica o Gemini.

Roteiro (decidido pelo corpo que o SDK envia): list_metrics -> query_metric(net_revenue por região, top 1) -> show_sql
-> texto montado com os números devolvidos pela ferramenta.
Uso: .venv/bin/python tests/support/serve_fake_gemini.py [--port 8001]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from google.genai import types  # noqa: E402
from pydantic import SecretStr  # noqa: E402

from app.api.main import create_app  # noqa: E402
from app.config import get_settings  # noqa: E402
from support.fake_gemini import call, function_responses, text  # noqa: E402

FAKE_KEY = "fake-key-for-scripted-transport-0000000000"


def responder(request: httpx.Request) -> httpx.Response:
    frs = function_responses(json.loads(request.content))
    if not frs:
        return httpx.Response(200, json=call("list_metrics"))
    last = frs[-1]
    if last["name"] == "list_metrics":
        return httpx.Response(200, json=call("query_metric", {
            "metric": "net_revenue", "dimensions": ["region"], "order_by": {"field": "metric", "direction": "desc"}, "limit": 1}))
    if last["name"] == "query_metric":
        out = last["response"].get("output")
        if out is None:
            return httpx.Response(200, json=text(f"Erro da ferramenta: {last['response']['error']['code']}"))
        return httpx.Response(200, json=call("show_sql", {"query_id": out["query_id"]}))
    q = next(f for f in frs if f["name"] == "query_metric")["response"]["output"]
    row = q["rows"][0]
    return httpx.Response(200, json=text(
        f"[roteiro falso, não é o Gemini] A região com maior receita líquida é {row['region']}, com R$ {row['value']} "
        f"(métrica {q['metric']}, query_id {q['query_id']})."))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8001)
    port = ap.parse_args().port
    settings = get_settings().model_copy(update={"gemini_api_key": SecretStr(FAKE_KEY), "gemini_model": "scripted-model"})
    opts = types.HttpOptions(httpx_client=httpx.Client(transport=httpx.MockTransport(responder)))
    uvicorn.run(create_app(settings, gemini_http_options=opts), host="127.0.0.1", port=port, workers=1)


if __name__ == "__main__":
    main()
