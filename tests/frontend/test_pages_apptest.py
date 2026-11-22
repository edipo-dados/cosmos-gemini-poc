"""Páginas Streamlit (AppTest) e serviço Streamlit real contra uma API uvicorn real (bancos e Cosmos reais, sem Gemini)."""
from __future__ import annotations
import json
import os
import socket
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[2]
FRONT = ROOT / "app" / "frontend"
PAGES = sorted((FRONT / "pages").glob("*.py"))
METRICS = ["gross_revenue", "net_revenue", "order_count", "average_order_value", "active_customers", "cancellation_rate",
           "refund_amount", "monthly_revenue_growth"]
GOLDEN = json.loads((ROOT / "tests" / "golden" / "expected.json").read_text())["cases"]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(url: str, timeout: float = 60) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise TimeoutError(url)


@pytest.fixture(scope="session")
def api_server(api_settings, tmp_path_factory):
    """uvicorn real em subprocesso, sobre os bancos e o World do Cosmos dos fixtures; sem GEMINI_API_KEY."""
    port = _free_port()
    env = {**os.environ, "COSMOS_WORLD_DIR": str(api_settings.cosmos_world_dir), "GEMINI_API_KEY": ""}
    log = open(tmp_path_factory.mktemp("uvicorn") / "uvicorn.log", "w")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.api.main:app", "--host", "127.0.0.1", "--port", str(port),
                             "--workers", "1"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    try:
        _wait(url + "/health")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=20)
        log.close()


@pytest.fixture()
def api_url(api_server, monkeypatch):
    monkeypatch.setenv("API_URL", api_server)
    monkeypatch.setenv("UI_USER_ID", "apptest")
    return api_server


def run_page(path: Path) -> AppTest:
    at = AppTest.from_file(str(path), default_timeout=90).run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def _text(at: AppTest) -> str:
    parts = [m.value for m in at.markdown] + [m.value for m in at.warning] + [m.value for m in at.info]
    parts += [e.label for e in at.expander] + [c.value for c in at.code] + [str(m.value) for m in at.metric]
    for df in at.dataframe:
        parts.append(df.value.to_csv())
    return "\n".join(str(p) for p in parts)


def golden(case_id: str) -> list[dict]:
    return next(c for c in GOLDEN if c["id"] == case_id)["rows"]


def test_five_pages_exist():
    assert [p.name for p in PAGES] == ["1_Analytics_Assistant.py", "2_Semantic_Catalog.py", "3_Data_Quality.py",
                                       "4_SQL_and_Evidence.py", "5_Data_Overview.py"]


def test_frontend_never_touches_databases_or_llm():
    forbidden = ("sqlalchemy", "psycopg", "duckdb", "google.genai", "app.db", "app.services", "agent.")
    for f in [*FRONT.glob("*.py"), *PAGES]:
        src = f.read_text()
        for line in src.splitlines():
            if line.startswith(("import ", "from ")):
                assert not any(x in line for x in forbidden), (f.name, line)


def test_home(api_url):
    at = run_page(FRONT / "Home.py")
    assert "Cosmos Analytics POC" in at.title[0].value
    assert any("não configurado" in str(m.value) for m in at.metric)


def test_assistant_without_key_shows_warning_and_direct_mode_works(api_url):
    at = run_page(FRONT / "pages" / "1_Analytics_Assistant.py")
    assert any("GEMINI_API_KEY" in w.value and "indisponível" in w.value for w in at.warning)
    assert not at.chat_input  # sem chave não há campo de chat
    at.selectbox(key="dm_metric").select("net_revenue")
    at.run()
    at.multiselect(key="dm_dims_net_revenue").select("region")
    at.button(key="dm_run").click()
    at.run()
    assert not at.exception
    text = _text(at)
    assert "SELECT" in text and "duckdb:analytics.duckdb" in text and "Sudeste" in text
    expected = {r["region"]: r["value"] for r in golden("net_revenue.by_region")}
    from app.frontend.formatting import format_brl
    assert format_brl(expected["Sudeste"]) in text


def test_catalog_shows_eight_metrics_and_glossary(api_url):
    at = run_page(FRONT / "pages" / "2_Semantic_Catalog.py")
    text = _text(at)
    for m in METRICS:
        assert m in text, m
    assert "Faturamento" in text and "Ticket" in text


def test_overview_kpis_match_golden(api_url):
    from app.frontend.formatting import format_value
    at = run_page(FRONT / "pages" / "5_Data_Overview.py")
    shown = {m.label: m.value for m in at.metric}
    for metric, case, label in (("gross_revenue", "gross_revenue.by_total", "Receita Bruta"),
                                ("net_revenue", "net_revenue.by_total", "Receita Líquida"),
                                ("order_count", "order_count.by_total", "Quantidade de Pedidos"),
                                ("active_customers", "active_customers.by_total", "Clientes Ativos"),
                                ("cancellation_rate", "cancellation_rate.by_total", "Taxa de Cancelamento"),
                                ("average_order_value", "average_order_value.by_total", "Ticket Médio")):
        raw = golden(case)[0]["value"]
        if metric in ("cancellation_rate", "average_order_value"):
            # razões: comparação numérica (golden é Decimal exato; a API devolve float)
            assert shown[label] == format_value(Decimal(str(raw)), metric, "ratio"), (label, shown[label], raw)
        else:
            assert shown[label] == format_value(raw, metric, None), (label, shown[label], raw)
    assert len(at.get("plotly_chart")) == 3


def test_data_quality_shows_runs_and_rules(api_url):
    at = run_page(FRONT / "pages" / "3_Data_Quality.py")
    text = _text(at)
    assert "duplicate_payments" in text and "customers" in text and "passed" in text


def test_sql_and_evidence_lists_audited_call(api_url):
    r = httpx.post(api_url + "/tools/query_metric", json={"metric": "order_count", "dimensions": ["payment_method"]},
                   headers={"X-User-Id": "apptest"})
    assert r.status_code == 200
    qid = r.json()["query_id"]
    at = run_page(FRONT / "pages" / "4_SQL_and_Evidence.py")
    assert len(at.dataframe) >= 1 and qid in at.dataframe[0].value["query_id"].tolist()
    at.selectbox(key="audit_pick").select(qid)
    at.run()
    text = _text(at)
    assert "SELECT" in text and "decisão de autorização" in text and qid in text


def test_pages_report_unreachable_api(monkeypatch):
    monkeypatch.setenv("API_URL", "http://127.0.0.1:9")
    at = AppTest.from_file(str(FRONT / "pages" / "2_Semantic_Catalog.py"), default_timeout=30).run()
    assert not at.exception
    assert any("API" in e.value for e in at.error)


def test_streamlit_service_health_and_page_served(api_server):
    port = _free_port()
    env = {**os.environ, "API_URL": api_server}
    proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app/frontend/Home.py", "--server.port", str(port),
                             "--server.headless", "true", "--server.address", "127.0.0.1"], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        _wait(f"http://127.0.0.1:{port}/_stcore/health")
        assert httpx.get(f"http://127.0.0.1:{port}/_stcore/health").text == "ok"
        assert httpx.get(f"http://127.0.0.1:{port}/").status_code == 200
    finally:
        proc.terminate()
        proc.wait(timeout=20)


@pytest.fixture(scope="session")
def scripted_chat_server(api_settings, tmp_path_factory):
    """API real com o SDK google-genai real e transporte roteirizado no lugar do Gemini (NÃO é o Gemini)."""
    port = _free_port()
    env = {**os.environ, "COSMOS_WORLD_DIR": str(api_settings.cosmos_world_dir)}
    log = open(tmp_path_factory.mktemp("scripted") / "scripted.log", "w")
    proc = subprocess.Popen([sys.executable, "tests/support/serve_fake_gemini.py", "--port", str(port)], cwd=ROOT, env=env,
                            stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    try:
        _wait(url + "/health")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=20)
        log.close()


def test_chat_renders_answer_numbers_sql_and_evidence_with_scripted_transport(scripted_chat_server, monkeypatch):
    """Exercita a interface do chat. A resposta vem do roteiro, não do Gemini: isto NÃO verifica o Gemini."""
    monkeypatch.setenv("API_URL", scripted_chat_server)
    monkeypatch.setenv("UI_USER_ID", "apptest-chat")
    at = run_page(FRONT / "pages" / "1_Analytics_Assistant.py")
    assert at.chat_input and not any("indisponível" in w.value for w in at.warning)
    at.chat_input[0].set_value("Qual região teve a maior receita?").run()
    assert not at.exception, [e.value for e in at.exception]
    text = _text(at)
    assert "Sudeste" in text and "SELECT" in text and "duckdb:analytics.duckdb" in text and "decisão de autorização" in text
    assert len(at.chat_message) == 2
