"""Ponta a ponta com o Gemini REAL (marcador live_gemini). Sem GEMINI_API_KEY, os testes ficam em skip.
Rodar: GEMINI_API_KEY=... GEMINI_MODEL=... .venv/bin/python -m pytest -m live_gemini -q"""
from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

pytestmark = [pytest.mark.live_gemini,
              pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="GEMINI_API_KEY ausente")]

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"
QUESTIONS = [q for q in json.loads((GOLDEN_DIR / "questions.json").read_text(encoding="utf-8"))["questions"]
             if "golden" in q["expect"]]
CASES = {c["id"]: c for c in json.loads((GOLDEN_DIR / "expected.json").read_text(encoding="utf-8"))["cases"]}


@pytest.fixture(scope="module")
def live_client(api_settings):
    from fastapi.testclient import TestClient
    from pydantic import SecretStr
    from app.api.main import create_app
    settings = api_settings.model_copy(update={"gemini_api_key": SecretStr(os.environ["GEMINI_API_KEY"]),
                                               "gemini_model": os.environ.get("GEMINI_MODEL", api_settings.gemini_model)})
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.mark.parametrize("q", QUESTIONS, ids=[q["id"] for q in QUESTIONS])
def test_live_question(live_client, q):
    r = live_client.post("/chat", json={"question": q["question"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "ok"
    expected = CASES[q["expect"]["golden"]]["rows"]
    if "top" in q["expect"]:
        expected = sorted(expected, key=lambda x: float(x["value"]), reverse=True)[: q["expect"]["top"]]
    values = {Decimal(str(v["value"])) for v in expected if v["value"] is not None}
    got = {Decimal(str(row["value"])) for qy in out["queries"] if qy["status"] == "ok" for row in qy["rows"] or []
           if row.get("value") is not None}
    assert values & got, (q["id"], out["answer"])
