# Relatório de aceite (Fase 6)

Execução em 2026-11-22, macOS arm64, Python 3.11.18, `.venv` do projeto, PostgreSQL 16.2 real via `pgserver`. Toda a execução usou `GEMINI_API_KEY=` vazia (o shell e o `.env` têm um valor definido, que foi sobrescrito em todos os comandos para não chamar o serviço). Docker não existe no ambiente.

## Estado limpo

Antes da execução, `pgdata/`, `analytics.duckdb`, `dq_lab.duckdb`, `logs/`, `.cosmos/` e `cosmos.environment.json` foram movidos para `/tmp/poc-backup-1795368000` (não apagados). O PostgreSQL foi parado antes. O `.env` foi mantido. Comandos completos em `docs/PHASE_REPORTS.md`, seção "Fase 6".

## Resumo

| # | Critério | Situação |
|---|---|---|
| 1 | PostgreSQL funcionando e populado | verificado por execução |
| 2 | DuckDB funcionando e populado | verificado por execução |
| 3 | Pipeline de carga executando | verificado por execução |
| 4 | Cosmos inicializado e integrado | verificado por execução |
| 5 | Gemini conectado com API Key | **não verificado** |
| 6 | Agente descobre conceitos e consulta métricas | verificado por execução só nas ferramentas; **escolha de ferramenta pelo Gemini não verificada** |
| 7 | Respostas numéricas iguais ao SQL de referência | verificado por execução no Query Engine e na API; **não verificado de ponta a ponta com o Gemini** |
| 8 | SQL inspecionável | verificado por execução |
| 9 | Evidências disponíveis | verificado por execução |
| 10 | Interface web funcional | verificado por execução (AppTest e serviço real); **não vista em navegador** |
| 11 | Testes automatizados passando | verificado por execução (os 14 testes ao vivo ficam em skip) |
| 12 | Aplicação inicia seguindo o README | verificado por execução, parcial: sem Docker e sem clone limpo |

## Evidências por critério

### 1. PostgreSQL funcionando e populado: verificado por execução
```
$ make pg-start migrate load        # saída de `load` (logs/generator.log)
INFO poc.generator gerando dados seed=42 fim=2026-10-31
INFO poc.generator oltp (linhas por tabela): {'categories': 20, 'regions': 5, 'customers': 5000, 'products': 500, 'orders': 20000, 'order_items': 47617, 'payments': 20000, 'refunds': 7194}
INFO poc.generator dq_lab (linhas por tabela): {... 'products': 501, 'orders': 437, 'order_items': 988, 'payments': 442, 'refunds': 164}
$ make load        # segunda execução
INFO poc.generator linhas novas inseridas em oltp: 0
```
Os volumes atendem ao enunciado (5.000 clientes, 500 produtos, 20 categorias, 5 regiões, 20.000 pedidos, 47.617 itens, 20.000 pagamentos). A segunda carga não duplicou nada. `tests/integration/test_migrations.py`, `test_load_idempotent.py` e `tests/security/test_pg_permissions.py` passaram.

### 2. DuckDB funcionando e populado: verificado por execução
```
$ make etl
INFO poc.etl ETL 1 iniciado: oltp -> /Users/edipo/projetos/poc-cosmos/analytics.duckdb
INFO poc.etl   dim_customer 5000 | dim_product 500 | dim_region 5 | dim_date 730
INFO poc.etl   fact_orders 20000 | fact_order_items 47617 | fact_payments 20000 | fact_refunds 7194
INFO poc.etl ETL 1 concluído em 252 ms
```

### 3. Pipeline de carga executando: verificado por execução
`make load`, `make etl` e `make quality` (acima e abaixo) rodam em sequência com logs em `logs/generator.log`, `logs/etl.log` e `logs/quality.log`. O ETL checa a qualidade da origem antes de construir o DuckDB ("0 violações"). Registro em `ops.*`: `GET /etl/runs` e `GET /quality/runs` responderam HTTP 200 (3 execuções de qualidade).

Qualidade e reconciliação:
```
$ make quality
oltp  regra cancelled_with_captured_payment violações=0 OK   (e as outras 6 regras: 0 violações)
oltp  reconciliação gross_revenue pg=30515235.50 duckdb=30515235.50 OK
oltp  reconciliação net_revenue   pg=26269632.31 duckdb=26269632.31 OK
oltp  reconciliação order_count   pg=20000 duckdb=20000 OK   (8 métricas OK)
dq_lab regra duplicate_payments violações=5 esperado=5 DETECTADO   (7 regras detectadas, contagens iguais às esperadas)
dq_lab divergência detectada=['average_order_value','gross_revenue','net_revenue'] esperado=[mesmo] OK
qualidade: TUDO OK
```

### 4. Cosmos inicializado e integrado: verificado por execução
```
$ .venv/bin/cosmos init .
[OK] Cosmos is active for poc-cosmos
$ make sync
"catalog_version": "54c809efd410", "written": true, "records_generated": 103,
"by_kind": {"actor": 2, "poc.dimension": 9, "poc.metric": 8, "poc.glossary_term": 18, "rule": 11, "edge": 48, "capability": 7},
"validate_graph_errors": []
$ .venv/bin/cosmos validate .
"node_count": 59, "edge_count": 50, "valid": true
```
Em `tests/integration/test_cosmos_sync.py` e `test_api.py` o conteúdo gravado no Cosmos é lido de volta, e cada chamada de ferramenta gera uma decisão de autorização, um resultado e um episódio no SQLite do Cosmos. A API respondeu `"cosmos":"ok"` em `/health`. O Cosmos guarda contexto, capacidades e trilha; não executa SQL (ver `docs/ARCHITECTURE.md`).

Teste de métricas contra SQL de referência: `make metric-tests` deu `21/21 testes de métrica passaram (catalog_version=54c809efd410)`.

### 5. Gemini conectado com API Key: não verificado
Nenhuma chamada ao Gemini real foi feita nesta execução, porque a chave foi deliberadamente esvaziada (ver cabeçalho). O código existe (`agent/gemini/`, 7 `FunctionDeclaration`, tratamento de 401/403/404/429/5xx) e é testado até a fronteira HTTP do SDK `google-genai`, com transporte roteirizado. `GET /health` mostrou `"gemini":"not_configured"` e `POST /ask` devolveu HTTP 503 `gemini_not_configured`. Os 14 testes `live_gemini` ficaram em skip:
```
$ GEMINI_API_KEY= pytest -m live_gemini -q -rs
SKIPPED [14] tests/live/test_live_gemini.py:32: GEMINI_API_KEY ausente
14 skipped, 266 deselected
```
Para verificar: `GEMINI_API_KEY=<chave válida> .venv/bin/python -m pytest -m live_gemini -q`.

### 6. Agente descobre conceitos e consulta métricas: parcial
Verificado por execução: as ferramentas que o agente usa (`search_concepts`, `explain_metric`, `list_metrics`, `list_dimensions`, `query_metric`) funcionam pela API e por `tests/integration/test_orchestration.py`, com o SDK real e roteiro escrito à mão. Exemplo real:
```
$ curl -X POST :8000/tools/query_metric -d '{"metric":"lucro"}'            -> HTTP 422 unknown_metric (lista as 8 métricas)
$ curl -X POST :8000/tools/query_metric -d '{"metric":"active_customers","dimensions":["category"]}'
HTTP 422 dimension_not_allowed, allowed_dimensions ["region","segment"]
$ curl -X POST :8000/tools/execute_sql -d '{"sql":"DROP TABLE fact_orders"}' -> HTTP 404 unknown_tool
```
Não verificado: que o Gemini real escolha essas ferramentas, preencha os argumentos e responda em português.

### 7. Números iguais ao SQL de referência: verificado por execução (sem Gemini)
`tests/integration/test_questions_golden.py` chama 19 perguntas pela API e compara com `tests/golden/expected.json` (SQL independente no PostgreSQL), com tolerância 0 em dinheiro e contagens. Passou na suíte completa. Exemplo na API real:
```
$ curl -X POST :8000/tools/query_metric -d '{"metric":"net_revenue","dimensions":["region"],"limit":1,"order_by":{"field":"metric","direction":"desc"}}'
rows [{"region":"Sudeste","value":"13063627.23"}]   (golden net_revenue.by_region: Sudeste 13063627.23)
$ curl -X POST :8000/tools/query_metric -d '{"metric":"net_revenue","date_from":"2026-10-02","date_to":"2026-10-31"}'
HTTP 200 rows [{"value":"876344.70"}]                (golden last_30_days: 876344.70)
```
`make golden` recalculou o arquivo: os valores são iguais aos versionados (só a ordem das linhas muda), e o arquivo versionado foi restaurado. Estes testes validam o Query Engine, não a interpretação do Gemini.

### 8. SQL inspecionável: verificado por execução
```
$ curl -X POST :8000/tools/show_sql -d '{"query_id":"47f6363b-..."}'
{"sql":"SELECT dr.region_name AS \"region\", COALESCE(SUM(i.line_total), 0) - COALESCE(SUM(rf.refund_amount), 0) AS \"value\" FROM fact_orders o JOIN fact_order_items i ON ... WHERE o.is_paid GROUP BY 1 OR..."
```

### 9. Evidências disponíveis: verificado por execução
```
$ curl :8000/evidence/47f6363b-...
HTTP 200 {"tool_name":"query_metric","metric":"net_revenue","dimensions":["region"],"filters":{"applied":[{"sql":"o.is_paid","rule":"Pedidos paid e refunded. ..."}], ...},"status":"ok","row_count":1, ...
```
A trilha fica em `audit.query_audit` e é lida por `GET /audit/queries`.

### 10. Interface web funcional: verificado por execução, sem navegador
- `pytest tests/frontend`: 14 passed (AppTest sobre uvicorn real: 5 páginas, KPIs iguais ao golden, aviso sem chave, consulta direta).
- Serviço real: `streamlit run app/frontend/Home.py --server.port 8501 --server.headless true` respondeu `/_stcore/health` HTTP 200 `ok` e `GET /` HTTP 200, com a API real na porta 8000 (`/overview` HTTP 200).
- Não verificado: aparência no navegador e chat com o Gemini real.

### 11. Testes automatizados passando: verificado por execução
```
$ make test      # pytest -m "not live_gemini" -q
266 passed, 14 deselected in 45.66s
```
Cobre unidade, integração, segurança de permissões, frontend e as 19 perguntas golden (ambígua, métrica inexistente, dimensão não autorizada e tentativa de injeção de SQL incluídas). Os 14 testes `live_gemini` não rodaram (critério 5).

### 12. Aplicação inicia seguindo o README: parcial
Executados nesta sessão os comandos do README seção 5: `bash scripts/bootstrap.sh` (idempotente, "Bootstrap concluído"), `make pg-start migrate load etl quality sync metric-tests`, uvicorn na porta 8000, Streamlit na 8501, `make test`. Limites: a execução foi no diretório de trabalho existente (com `.venv`, `.vendor` e `.env` já presentes), não em um clone limpo; o `bootstrap.sh` não foi exercitado do zero. O caminho Docker do README (seção 6) **não foi executado**: não há Docker no ambiente, e só a análise estática do Compose e do Dockerfile passou.

## Não verificado

- Gemini real (critérios 5, 6 e parte do 7): sem chave utilizada.
- Docker, `docker compose config/build/up` e o encaixe do World no volume.
- Interface em navegador.
- Instalação em clone limpo e do zero.
- Desempenho sob carga: só a consulta de 1,5 s com `/health` abaixo de 1 s (testada na Fase 4).
- O 504 `query_timeout` na API (o timeout está testado no Query Engine).

## Divergência de ambiente

O enunciado dizia que `GEMINI_API_KEY` não estava definida, mas o shell e o `.env` têm um valor de 53 caracteres. Ele não foi usado nesta fase. A Fase 4 registra uma chamada acidental anterior, que recebeu HTTP 402 do serviço.

## Achados não resolvidos e riscos conhecidos

Revisão da Fase 6: APPROVED. Achados de baixa gravidade, não bloqueantes:
- README §2 dizia que o Gemini "nunca vê SQL", mas `show_sql` devolve o SQL ao modelo. Texto corrigido para "não escreve SQL nem acessa banco".
- Data da execução (2026-11-22, conferida: 17:20 UTC) e o backup `/tmp/poc-backup-1795368000` (existe) conferidos.

Riscos conhecidos:
- Gemini real nunca exercitado com chave válida (critérios 5, 6 e parte do 7). Uma chamada acidental na Fase 4 recebeu HTTP 402.
- Docker/Compose não executado; World do Cosmos em volume de contêiner não verificado (`cosmos init` sem `.git` falha).
- Cosmos em "Developer Preview", fixado por commit; `transition_episode` é API interna, coberta por teste de contrato.
- O sync grava conhecimento já `active` (sem fluxo `candidate` → `validated` → `active`).
- Interface não vista em navegador; clone limpo e `bootstrap.sh` do zero não exercitados; timeout 504 da API e desempenho sob carga sem teste.
- `frozen_core_intact: false` e `doctor` em FAIL são esperados nesta instalação.
