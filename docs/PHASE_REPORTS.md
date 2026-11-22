# Relatórios de fase

## Fase 2: Data Foundation

Critérios fechados por execução real: **1** (PostgreSQL populado), **2** (DuckDB populado), **3** (pipeline de carga com logs).
Ambiente: macOS arm64, CPython 3.11.18 (`.venv`), PostgreSQL 16.2 real (binários do `pgserver`, TCP `127.0.0.1:54329`), DuckDB 2.0.1 em arquivo persistente. Sem Docker, sem `GEMINI_API_KEY`. Nada foi mockado.

### O que foi entregue

| Item | Onde |
|---|---|
| Dependências fixadas e lock | `requirements.txt` (todas as versões da seção 12 do ARCHITECTURE instalaram sem troca), `requirements.lock.txt` (`uv pip compile`) |
| Configuração, logging com redação de segredos, engines por papel | `app/config.py`, `app/logging_setup.py`, `app/db.py` |
| PostgreSQL local sem Docker | `scripts/pg_local.py start\|stop\|status` (usa `initdb`/`pg_ctl` do `pgserver`; a API Python do `pgserver` só abre socket Unix, por isso o TCP é configurado com `pg_ctl -o "-p 54329 -h 127.0.0.1"`) |
| Migrações | `database/migrate.py`, `database/migrations/001..006*.sql` (papéis, `oltp`, `dq_lab`, `audit`, `ops`, grants). Senhas só do ambiente, aplicadas por `ALTER ROLE` com quoting no servidor |
| Gerador Faker `pt_BR`, determinístico | `data/generators/*` (`python -m data.generators.run --seed 42 [--reset]`) |
| ETL PostgreSQL → DuckDB | `pipelines/extract/postgres_extract.py`, `pipelines/transform/{schema,build_duckdb,run}.py` |
| Regras de qualidade e reconciliação | `pipelines/quality/rules/*.sql` (7), `reference_sql/*.sql` (8, PostgreSQL), `duckdb_sql/*.sql` (8, DuckDB), `runner.py`, `reconcile.py`, `run.py` |
| Testes | `tests/unit`, `tests/integration`, `tests/security` (37 testes) |
| Atalhos | `Makefile` (`pg-start migrate load etl quality test data`), `scripts/bootstrap.sh`, `.env.example` |

### Decisões desta fase

- Dados oficiais (`oltp`) são válidos: PKs, FKs, UNIQUEs, CHECKs e índices. Defeitos controlados vivem só em `dq_lab` (mesmas colunas, só PKs), com amostra válida de 400 pedidos mais defeitos em pedidos novos (ids ≥ 1.000.001). Contagens esperadas por regra em `tests/golden/dq_expected.json`.
- Reembolso ≤ valor pago não é expressável como CHECK entre tabelas; é coberto pela regra `refund_exceeds_paid` (que também confere reembolso > total do item).
- O ETL executa as 7 regras em `oltp` (papel `poc_dq`) e **aborta antes da troca do arquivo** se houver violação. O arquivo é montado em `analytics.duckdb.tmp` e trocado por `os.replace`.
- Divergência PostgreSQL × DuckDB: a reconciliação usa SQL escrita à mão nos dois lados (independente do Query Engine, que é da Fase 3). Dinheiro e contagens: tolerância 0 (comparação `Decimal`). Razões e quocientes (`average_order_value`, `cancellation_rate`, `monthly_revenue_growth`): tolerância absoluta 1e-9. `average_order_value` entra como quociente porque a divisão em `double` pode diferir na última casa.
- A divergência demonstrada é determinística: `dq_lab.duckdb` é construído a partir de `dq_lab` e perde o item `tampered_order_item_id` (manifesto). Divergem exatamente `gross_revenue`, `net_revenue` e `average_order_value`. `monthly_revenue_growth` não diverge porque o item adulterado está no primeiro mês e o mês seguinte do `dq_lab` tem receita 0 nos dois lados (razão -1 igual); o manifesto registra só as três.
- `dim_date` cobre 2024-11-01 a 2026-10-31 (730 dias).

### Execução do zero (comandos e saídas reais)

Estado limpo: `make pg-stop; rm -rf pgdata analytics.duckdb dq_lab.duckdb logs`. Depois:

```
$ make pg-start
PostgreSQL em execução em 127.0.0.1:54329 (datadir=.../pgdata)

$ make migrate
INFO poc.migrate banco analytics_poc criado
INFO poc.migrate migração aplicada: 001_roles_schemas
INFO poc.migrate migração aplicada: 002_oltp
INFO poc.migrate migração aplicada: 003_dq_lab
INFO poc.migrate migração aplicada: 004_audit
INFO poc.migrate migração aplicada: 005_ops
INFO poc.migrate migração aplicada: 006_grants
$ make migrate        # segunda execução
INFO poc.migrate nenhuma migração pendente

$ make load           # python -m data.generators.run --seed 42
INFO poc.generator gerando dados seed=42 fim=2026-10-31 (hash 4865c6f00267d2e0)
INFO poc.generator oltp (linhas por tabela): {'categories': 20, 'regions': 5, 'customers': 5000, 'products': 500, 'orders': 20000, 'order_items': 47617, 'payments': 20000, 'refunds': 7194}
INFO poc.generator dq_lab (linhas por tabela): {'categories': 20, 'regions': 5, 'customers': 5000, 'products': 501, 'orders': 437, 'order_items': 988, 'payments': 442, 'refunds': 164}
INFO poc.generator linhas novas inseridas em oltp: 100336

$ make load           # IDEMPOTÊNCIA: mesma seed de novo
INFO poc.generator oltp (linhas por tabela): {... mesmas contagens ...}
INFO poc.generator linhas novas inseridas em oltp: 0

$ python -m data.generators.run --seed 7      # seed diferente sem --reset
ERROR poc.generator dados já carregados com seed=42 hash=4865c6f00267d2e0; pedido seed=7 hash=e3b7e79aaebdee17. Use --reset para recarregar.
EXIT=2

$ make etl
INFO poc.etl ETL 1 iniciado: oltp -> .../analytics.duckdb
INFO poc.etl extraído de oltp: {'categories': 20, 'regions': 5, 'customers': 5000, 'products': 500, 'orders': 20000, 'order_items': 47617, 'payments': 20000, 'refunds': 7194}
INFO poc.etl qualidade de oltp: 0 violações, construindo DuckDB
INFO poc.etl   dim_customer          5000 linhas
INFO poc.etl   dim_product            500 linhas
INFO poc.etl   dim_region               5 linhas
INFO poc.etl   dim_date               730 linhas
INFO poc.etl   fact_orders          20000 linhas
INFO poc.etl   fact_order_items     47617 linhas
INFO poc.etl   fact_payments        20000 linhas
INFO poc.etl   fact_refunds          7194 linhas
INFO poc.etl ETL 1 concluído em 276 ms
$ make etl            # ETL 2: mesmo conteúdo, novo etl_run_id (2)
```

Logs de arquivo (git-ignorados): `logs/etl.log`, `logs/generator.log`, `logs/quality.log`. A migração loga só no console.

### `make quality` (regras e reconciliação)

```
oltp   regra cancelled_with_captured_payment  violações=0 OK
oltp   regra duplicate_payments               violações=0 OK
oltp   regra inconsistent_dates               violações=0 OK
oltp   regra items_without_product            violações=0 OK
oltp   regra negative_values                  violações=0 OK
oltp   regra orders_without_customer          violações=0 OK
oltp   regra refund_exceeds_paid              violações=0 OK
oltp   reconciliação gross_revenue            pg=30515235.50 duckdb=30515235.50 OK
oltp   reconciliação net_revenue              pg=26269632.31 duckdb=26269632.31 OK
oltp   reconciliação refund_amount            pg=4245603.19 duckdb=4245603.19 OK
oltp   reconciliação order_count              pg=20000 duckdb=20000 OK
oltp   reconciliação active_customers         pg=1424 duckdb=1424 OK
oltp   reconciliação average_order_value      pg=1585.1817710596185 duckdb=1585.1817710596185 OK
oltp   reconciliação cancellation_rate        pg=0.1169 duckdb=0.1169 OK
oltp   reconciliação monthly_revenue_growth   24 meses nos dois lados, iguais OK
dq_lab regra cancelled_with_captured_payment  violações=4 esperado=4 DETECTADO
dq_lab regra duplicate_payments               violações=5 esperado=5 DETECTADO
dq_lab regra inconsistent_dates               violações=7 esperado=7 DETECTADO
dq_lab regra items_without_product            violações=6 esperado=6 DETECTADO
dq_lab regra negative_values                  violações=6 esperado=6 DETECTADO
dq_lab regra orders_without_customer          violações=7 esperado=7 DETECTADO
dq_lab regra refund_exceeds_paid              violações=3 esperado=3 DETECTADO
dq_lab reconciliação gross_revenue / net_revenue / average_order_value  DIVERGE (esperado)
dq_lab reconciliação refund_amount / order_count / active_customers / cancellation_rate / monthly_revenue_growth  igual
dq_lab divergência detectada=['average_order_value','gross_revenue','net_revenue'] esperado=igual OK
qualidade: TUDO OK      (exit 0)
```

Reconciliação 8/8 em `oltp` × `analytics.duckdb`. Histórico gravado em `ops.dq_run`/`ops.dq_result`.

### Conferência direta por SQL (independente do código do projeto)

Consultas como `poc_admin` no PostgreSQL e abrindo `analytics.duckdb` com `duckdb` em modo leitura:

```
PostgreSQL 16.2 on aarch64-apple-darwin
oltp.customers 5000 | products 500 | categories 20 | regions 5
oltp.orders 20000 | order_items 47617 | payments 20000 | refunds 7194
orders por status: cancelled 2338, paid 14755, pending 1090, refunded 1817
payments por método: boleto 2944, credit_card 8987, debit_card 2007, pix 6062
refunds por status: completed 6105, pending 599, rejected 490
order_date: 2024-11-01 a 2026-10-31, 24 meses distintos
ops.etl_run: (1, success, 276 ms), (2, success, 269 ms)
ops.dq_run: oltp/etl passed (x2), oltp/cli passed, dq_lab/cli passed
DuckDB: dim_customer 5000, dim_product 500, dim_region 5, dim_date 730,
        fact_orders 20000, fact_order_items 47617, fact_payments 20000, fact_refunds 7194
etl_meta.etl_run_id = 2 ; SUM(line_total) de pedidos pagos = 30515235.50 (igual ao PostgreSQL)
```

### Testes

```
$ .venv/bin/python -m pytest -q
37 passed in 31.66s
```

A suíte sobe um PostgreSQL real próprio (cluster temporário, porta livre, senhas aleatórias), migra, gera, carrega, roda o ETL e testa. Cobre:

- `unit/test_generators.py`: mesma seed ⇒ DataFrames idênticos; seed diferente difere; volumes, status, 4 métodos, 24 meses; `oltp` sem defeitos; `refunded` ⇔ todos os itens reembolsados integralmente.
- `integration/test_migrations.py`: segunda migração é no-op; PKs/FKs/CHECKs/índices em `oltp`; `dq_lab` sem FKs/CHECKs; PostgreSQL 16; violação de FK/CHECK/UNIQUE rejeitada.
- `integration/test_load_idempotent.py`: contagens lidas do PostgreSQL por SQL; rerun insere 0; outra seed sem `--reset` retorna 2 e não altera; `--reset` recarrega o mesmo conteúdo; manifesto igual ao golden versionado.
- `integration/test_etl.py`: 8 tabelas e contagens iguais às de `oltp`; `etl_meta.etl_run_id` = `ops.etl_run.id`; segundo ETL muda o id e preserva o conteúdo; ETL com defeito injetado (pedido cancelado com pagamento capturado) aborta com `QualityGateError`, mantém o arquivo anterior byte a byte, registra `failed`; SQL de extração só referencia `oltp`; log em arquivo sem senhas.
- `integration/test_quality.py`: 7 regras em `dq_lab` = manifesto; `oltp` = 0; reconciliação 8/8; execução completa gravada em `ops`; divergência detectada.
- `integration/test_isolation.py`: `poc_reader` não lê `dq_lab`; métricas oficiais no DuckDB não mudam depois de recarregar `dq_lab`.
- `security/test_pg_permissions.py`: `poc_reader` falha em `INSERT` e em `SELECT dq_lab`/`audit`; `poc_loader` sem DDL e sem `audit`; `poc_dq` sem escrita em `oltp`; `poc_app` falha em `UPDATE`/`DELETE` de `audit.query_audit`, `DELETE` em `chat_turn`, `UPDATE question`, transição `ok → error`; `started → ok` funciona; FK de `query_audit.turn_id` existe.

### Não verificado nesta fase

- Docker e Docker Compose (indisponíveis). `database/postgres/init/001_roles_schemas.sql` é só uma cópia dos papéis para o compose e não foi executada via contêiner.
- Gemini e Cosmos (Fases 3 e 4).
- `scripts/bootstrap.sh` cobre só a instalação de dependências; a parte do Cosmos entra na Fase 3. Não foi reexecutado em clone limpo.
- Tabelas `audit.*` foram criadas e têm permissões testadas, mas ainda não são gravadas pela aplicação (Fase 3).

Nada foi commitado nesta etapa.

## Fase 3: Semantic Governance com sync para o Cosmos
Critério fechado por execução real: **4** (Cosmos inicializado e integrado conforme recursos comprovados). Critério **7** fechado no nível do motor (8 métricas contra SQL independente no PostgreSQL). Ambiente: o mesmo da Fase 2 (PostgreSQL 16.2 real via pgserver, DuckDB 2.0.1, Cosmos `464175f` instalado em modo editável, sem Docker, `GEMINI_API_KEY` ausente). Nada foi mockado: PostgreSQL, DuckDB e Cosmos (World real, servidor MCP real, `ToolAdapter` e `AuthorizationGateway` reais) rodaram de verdade.
### O que foi entregue
| Item | Onde |
|---|---|
| Catálogo versionado: 8 métricas (nome técnico e de negócio, descrição, fórmula, fonte, dimensões permitidas, filtros aplicáveis, responsável, versão, testes, denominador, regra de status, base de tempo) | `semantic/metrics/*.yaml` |
| 9 dimensões (data, mês, ano, região, segmento, categoria, produto, forma de pagamento, status) | `semantic/dimensions/*.yaml` |
| Fontes e junções do DuckDB (único lugar com nomes de tabela) | `semantic/sources.yaml` |
| 11 regras de negócio (denominadores, status, janelas, base de tempo, atribuição, precisão, governança) | `semantic/rules/business_rules.yaml` |
| Glossário pt-BR: 18 termos, sinônimos, "Receita" ambígua apontando para bruta e líquida | `semantic/glossary/glossary.yaml` |
| 7 ferramentas permitidas (geram os nós `capability`) | `semantic/rules/agent_capabilities.yaml` |
| Esquemas JSON e loader com `catalog_version` (hash do conteúdo) e validação cruzada | `semantic/schema/*.json`, `semantic/loader.py` |
| Query Engine: validação, SQL parametrizado, execução somente leitura em DuckDB, evidências | `app/services/query_engine/{validation,sql_builder,executor,service,errors}.py` |
| Sync YAML → World do Cosmos | `semantic/sync_to_cosmos.py` |
| Testes de validação declarados nas métricas (21) | `semantic/metric_tests.py` |
| Golden por SQL independente no PostgreSQL (61 casos) | `scripts/compute_golden.py`, `tests/golden/expected.json` |
| Bootstrap do Cosmos no commit fixado e `cosmos init` | `scripts/bootstrap.sh` |
| Relação YAML ↔ Cosmos e tabela proven/unproven | `cosmos/documentation/USO_DO_COSMOS.md` |
| Atalhos | `make sync golden metric-tests` |
### Decisões desta fase
- **Fonte de verdade**: o YAML. O Query Engine só lê o YAML, nunca o grafo. O Cosmos recebe uma projeção (ver `USO_DO_COSMOS.md`).
- **Sem SQL livre**: identificadores (tabelas, colunas, expressões, junções, aliases) vêm só do YAML. Valores de filtro, datas e limite entram como parâmetros `?`. Valores categóricos são conferidos contra o DuckDB (cache por `etl_run_id`). `assert_single_select` exige uma instrução `SELECT/WITH`. A garantia real de leitura é `duckdb.connect(read_only=True)` por requisição.
- **Classificação de erros**: falha de esquema (tipo, campo extra, regex) vira `invalid_arguments`; falha de domínio usa os códigos `unknown_metric`, `dimension_not_allowed`, `invalid_dimension_combination`, `missing_required_dimension`, `invalid_filter`, `invalid_date_range`, `invalid_order`, `invalid_limit`, `query_timeout`.
- **`monthly_revenue_growth`**: calendário completo (24 meses) crossjoin dos valores da região e do segmento pedidos; `LAG` antes do filtro de data; `date_from` e `date_to` só limitam os meses devolvidos.
- **`active_customers`**: janela `[as_of - 89, as_of]`; `as_of` = `date_to` ou `DATA_END_DATE` (2026-10-31), nunca a data do sistema; `date_from` é rejeitado.
- **Proveniência no Cosmos**: `created_by` (ator do `cosmos init`) mais `imported_from` com o arquivo YAML e o `catalog_version`; `authority.class = external`.
- **Fora desta fase**: `ToolExecutor`, `SemanticReader`, auditoria em `audit.query_audit` e o adaptador de 7 ferramentas (itens 3.6 do plano) não foram implementados. O escopo pedido foi catálogo, Query Engine e sync. O gateway foi provado no teste de sync com um provider mínimo escrito no próprio teste.
### Execução (comandos e saídas reais)
World do projeto: `bash scripts/bootstrap.sh` (reexecução é no-op: "Checked 18 packages"), `cosmos init .` criou `cosmos.environment.json` e `.cosmos/` (ignorados pelo git). Hooks `.githooks/` removidos (apontam para caminho Windows).
```
$ make sync
{ "catalog_version": "54c809efd410", "written": true, "changed_records": 103, "removed_stale": 0, "records_generated": 103,
  "by_kind": {"actor": 2, "poc.dimension": 9, "poc.metric": 8, "poc.glossary_term": 18, "rule": 11, "edge": 48, "capability": 7},
  "preserved_foreign_records": 6, "validate_graph_errors": [] }
$ .venv/bin/cosmos validate .
{ "edge_count": 50, "node_count": 59, "environment_id": "cosmos:environment:developer:poc-cosmos", "valid": true }
$ make sync   # 2a execução
"written": false, "changed_records": 0        # md5 de .cosmos/graph.json idêntico antes e depois (9aa66f04...)
```
Leitura de volta pelo servidor MCP do Cosmos (subprocesso, `COSMOS_GRAPH` absoluto e `cwd` fixos) sobre o World do projeto:
```
cosmos_query {"where":{"id": metric_id("net_revenue")}} -> count 1, display_name net_revenue, aliases ['Receita Líquida'], version 1.0.0, owner Finanças,
  provenance imported_from {system: poc-semantic-catalog, uri: semantic/metrics/net_revenue.yaml, revision: 54c809efd410}
cosmos_explain net_revenue -> regras governed_by: Status do pedido, Consultas governadas, Valores monetários, Atribuição por categoria e produto,
  Base de tempo, Pedido pago, Reembolso efetivado
cosmos_tool -> 7 capabilities
```
Testes de métrica declarados no catálogo (SQL de referência no PostgreSQL `oltp` via `poc_reader` contra o Query Engine em DuckDB):
```
$ .venv/bin/python -m semantic.metric_tests
OK   gross_revenue            total_vs_reference_sql   referência=30515235.50 motor=30515235.50
OK   net_revenue              total_vs_reference_sql   referência=26269632.31 motor=26269632.31
OK   order_count              total_vs_reference_sql   referência=20000 motor=20000
OK   average_order_value      total_vs_reference_sql   referência=1585.1817710596185 motor=1585.1817710596185
OK   active_customers         total_vs_reference_sql   referência=1424 motor=1424
OK   cancellation_rate        total_vs_reference_sql   referência=0.1169 motor=0.1169
OK   refund_amount            total_vs_reference_sql   referência=4245603.19 motor=4245603.19
OK   monthly_revenue_growth   series_vs_reference_sql  24 chave(s) comparada(s), 0 divergência(s)
(+ 13 invariantes: aditividade por região/segmento/status, faixa 0 a 1, líquida <= bruta, primeiro mês NULL)
21/21 testes de métrica passaram (catalog_version=54c809efd410)
$ .venv/bin/python scripts/compute_golden.py
61 casos gravados em tests/golden/expected.json
```
### Testes
```
$ .venv/bin/python -m pytest -m "not live_gemini" -q
174 passed in 37.08s          # 37 da Fase 2 + 137 desta fase
```
Novos arquivos e o que cobrem:
- `unit/test_semantic_catalog.py`: esquema; matriz métrica × dimensão igual à tabela do ARCHITECTURE; owner, versão e testes em todas as métricas; "receita" mapeia para as duas métricas; sinônimos exigidos; `catalog_version` estável e sensível ao conteúdo; YAML inválido rejeitado.
- `unit/test_validation.py`, `unit/test_sql_builder.py`: códigos de erro, injeção em filtros, dimensões e `order_by` (nada vai ao SQL), parâmetros `?`, janela de 90 dias, `LAG` antes do filtro de data, rejeição de `DELETE/DROP/ATTACH/;`.
- `integration/test_query_engine.py`: DuckDB real; evidências (SQL, parâmetros, filtros, versões, `etl_run_id` igual a `etl_meta`); injeção; `active_customers` com `date_to` e `date_from` rejeitado; crescimento com janela, `order_by`, `limit`; conexão `read_only` (CREATE e DELETE falham); **timeout real**: consulta `range(1e10)` interrompida por `interrupt()` com `query_timeout` em menos de 5 s e conexão ainda utilizável; novo ETL é visto sem reiniciar.
- `integration/test_metrics_reconciliation.py`: 61 casos do golden (por métrica e por região, mês, ano, categoria, produto, forma de pagamento, status, segmento, com filtros e janelas) com tolerância 0 em dinheiro e contagens e 1e-9 em razões; os 21 testes declarados; prova negativa (fórmula de `net_revenue` sem reembolsos faz o teste declarado falhar).
- `integration/test_cosmos_sync.py`: World descartável real; `validate_graph == []` e `cosmos validate` `valid: true`; MCP em subprocesso com `count > 0` antes de comparar; 8 métricas, 9 dimensões, glossário, regras, versões e proveniência iguais ao YAML; `cosmos_explain` lista as regras por `core.governed_by`; idempotência (arquivo idêntico, registros do `cosmos init` preservados); alteração de YAML muda o grafo (`updated_at`); regra e sinônimo removidos saem do grafo sem arestas órfãs; `ToolAdapter` + `AuthorizationGateway` reais permitem a ferramenta declarada, negam a não declarada e passam a negar uma ferramenta removida do YAML depois do sync; sem World, código 2 e nada é criado.
### Itens verificados e não verificados
Verificado por execução: sync com `validate_graph` e `cosmos validate`; leitura pelo MCP real; idempotência; propagação de mudanças e remoções; gateway permitindo e negando conforme os nós sincronizados; reconciliação das 8 métricas por 61 casos e 21 testes declarados; timeout; somente leitura; injeção rejeitada.
Não verificado ou não feito:
- **`SemanticReader` e `explain_metric` sobre o grafo do sync real**: não implementados nesta fase (item 3.6). O que está provado é a base: `cosmos_explain` e `cosmos_query` do Cosmos devolvem os dados do sync real. O formato de erro de `tool_explain` com grafo inválido continua provado só pelo spike da Fase 1.
- Fluxo oficial de admissão de conhecimento (Candidate Intake): contornado. O sync grava `active` direto (declarado em `USO_DO_COSMOS.md`).
- O gateway carregar sozinho os nós `capability`: UNPROVEN; o provider é código do projeto (no teste).
- Busca por sinônimo no MCP: UNPROVEN (o MCP não filtra `aliases`); o glossário e os `aliases` estão no grafo para o adaptador da Fase 4.
- `scripts/cosmos_world_init.sh` (container) não foi escrito; Docker indisponível.
- Gemini: nada nesta fase depende dele.
Nada foi commitado nesta etapa, conforme instrução.

## Fase 4: Integração Gemini + FastAPI

### O que foi entregue
- `agent/gemini/`: cliente com o SDK oficial `google-genai` 3.6.1 (`genai.Client(api_key=...)`), `GenerateContentConfig` com temperatura 0, instrução de sistema em pt-BR, as 7 `FunctionDeclaration` e `AutomaticFunctionCallingConfig(disable=True)`. Novas tentativas para 429 e 5xx (esperas de 1 s e 2 s). Mapeamento de erros: 401/403 (e 400 "API key not valid") para `gemini_auth_failed` (503), 404 para `gemini_model_invalid` (503), demais para `llm_unavailable` (502). Resposta bloqueada vira `status: blocked`. Sem chave: `gemini_not_configured` (503).
- `agent/gemini/declarations.py`: declarações geradas dos modelos Pydantic de `agent/tools/schemas.py` (`Schema.from_json_schema`). Nenhum parâmetro aceita SQL ou nome de tabela. `cosmos_open` e `cosmos_act` não são expostos.
- `agent/orchestration/`: loop manual de Function Calling, com no máximo 6 rodadas de ferramentas (`incomplete` quando estoura) e histórico em memória de até 20 turnos por `session_id`. Cada pergunta abre um episódio no Cosmos com `idempotency_key=turn_id`. O fim leva o episódio a `COMPLETED`, ou a `FAILED` em erro, e grava `audit.chat_turn` de `started` para o status final.
- `agent/tools/`: `ToolExecutor` (esquema → `new_attempt`/`authorize_effect` do `AuthorizationGateway` → domínio fora do lock → `ToolAdapter.execute` → auditoria em `finally`), `CosmosRuntime` (provider que lê os nós `capability` do grafo e nega tudo quando não consegue ler, handoff por `query_id`), `SemanticReader` (lê `.cosmos/graph.json` por caminho explícito; `explain_metric` via `tool_explain` do MCP do Cosmos).
- `app/services/audit.py`: `audit.query_audit` e `audit.chat_turn` com o papel `poc_app`.
- `app/api/`: FastAPI com endpoints `def` síncronos. `GET /health`, `POST /chat` e o alias `POST /ask`, `POST /tools/{name}`, `GET /evidence/{query_id}`, `GET /catalog/metrics`, `GET /catalog/dimensions`, `GET /catalog/glossary`. Limite de corpo de 16 KiB (413), `X-User-Id` validado, corpo de erro único `{"error":{"code","message"}}`.
- `tests/golden/questions.json`: 19 perguntas em pt-BR, cobrindo as 7 perguntas exemplo do TASK, uma ambígua, uma métrica inexistente (`lucro`), uma dimensão não autorizada e uma tentativa de injeção. `scripts/compute_golden.py` ganhou 2 casos (últimos 30 dias e últimos dois meses), totalizando 63 casos em `expected.json`; os 61 anteriores ficaram idênticos.
- `tests/support/fake_gemini.py`: transporte `httpx.MockTransport` passado ao SDK por `HttpOptions(httpx_client=...)`. O SDK real monta a requisição e interpreta a resposta; só a fronteira HTTP é falsa. `tests/support/serve_fake_gemini.py` sobe a mesma API em uvicorn com esse transporte.

### Leitura da API instalada do `google-genai` (item 4.1)
```
$ .venv/bin/python -c "import google.genai as g; print(g.__version__)"
3.6.1
AutomaticFunctionCallingConfig fields: disable, maximum_remote_calls, ignore_call_history
GenerateContentConfig: system_instruction, temperature, tools, tool_config, automatic_function_calling, safety_settings, ...
FunctionDeclaration fields: description, name, parameters, parameters_json_schema, response, response_json_schema, behavior
errors.APIError(code, response_json, response=None); ClientError e ServerError herdam de APIError
HttpOptions: base_url, api_version, headers, timeout, retry_options, httpx_client, ...
```
Com um transporte falso, o SDK envia `POST https://generativelanguage.googleapis.com/v1/models/<modelo>:generateContent`, com a chave no cabeçalho `x-goog-api-key`, `tools[0].functionDeclarations`, `generationConfig.temperature = 0` e `toolConfig.functionCallingConfig.mode = AUTO`. Um 429 do servidor vira `ClientError` com `code=429`. Esse comportamento foi conferido em `tests/unit/test_gemini_declarations.py::test_sdk_serializes_declarations_on_the_wire`.

### Decisões desta fase
- Falha ao ler o grafo bloqueia antes de chegar ao `SemanticReader`. Com `graph.json` ilegível, o provider nega tudo e a resposta é 403 `tool_not_authorized`. `semantic_catalog_unavailable` (503) aparece quando o grafo é legível e não tem nós `poc.metric`. Os dois casos estão testados.
- `explain_metric` confere a existência da métrica no YAML (fonte de verdade) e depois lê o grafo. Uma métrica que existe no YAML e falta no grafo dá 500 `internal_error`.
- Uma chamada de ferramenta com nome desconhecido, vinda do modelo, volta ao modelo como `unknown_tool` e não gera linha de auditoria, como define a seção 6.1.
- Em `/chat`, os erros `cosmos_runtime_unavailable`, `semantic_catalog_unavailable` e `audit_failed` encerram a pergunta (503/500). Os demais erros de ferramenta voltam ao modelo como resposta da função.

### Execução por HTTP real (uvicorn)
Roteiro descartável `/tmp/phase4_http_check.py`. Ele sobe dois processos uvicorn contra os bancos do projeto e o World do projeto, chama os endpoints com `curl` e encerra os dois:
1. `GEMINI_API_KEY= .venv/bin/python -m uvicorn app.api.main:app --port 8000`
2. `.venv/bin/python tests/support/serve_fake_gemini.py --port 8001`, com o SDK real e um transporte roteirizado que **não é o Gemini**.
```
$ curl http://127.0.0.1:8000/health
HTTP 200 {"status":"ok","gemini":"not_configured","gemini_model":null,"postgres":"ok","duckdb":"ok","cosmos":"ok","catalog_version":"54c809efd410","etl_run_id":2}
$ curl -X POST :8000/chat -d '{"question":"Qual foi o faturamento dos últimos 30 dias?"}'
HTTP 503 {"error":{"code":"gemini_not_configured","message":"GEMINI_API_KEY não está definida no ambiente. O chat está indisponível; as ferramentas continuam acessíveis em POST /tools/{name}."}}
$ curl -X POST :8000/ask ...                                  -> HTTP 503 gemini_not_configured
$ curl :8000/catalog/metrics                                  -> HTTP 200 count 8 (fórmula, denominador, responsável, versão, regras)
$ curl :8000/catalog/glossary                                 -> HTTP 200 count 18; "Receita": sinônimos Faturamento, Vendas...; maps_to gross_revenue e net_revenue
$ curl :8000/catalog/dimensions                               -> HTTP 200 count 9
$ curl -X POST :8000/tools/query_metric -d '{"metric":"net_revenue","date_from":"2026-10-02","date_to":"2026-10-31"}'
HTTP 200 rows [{"value":"876344.70"}]   (golden net_revenue.last_30_days = 876344.70)
$ curl -X POST :8000/tools/show_sql -d '{"query_id":"62060a1b-..."}'
HTTP 200 "sql":"SELECT COALESCE(SUM(i.line_total), 0) - COALESCE(SUM(rf.refund_amount), 0) AS \"value\" FROM fact_orders o JOIN fact_order_items i ... WHERE o.is_paid AND o.order_date >= CAST(? AS DATE) AND o.order_date <= CAST(? AS DATE) LIMIT ?","params":["2026-10-02","2026-10-31",101]
$ curl :8000/evidence/62060a1b-...
HTTP 200 status ok, etl_run_id 2, catalog_version 54c809efd410, cosmos_episode_id run_5ddd43f5..., cosmos_decision_id authz_3f8239a7..., evidence {rules, filters_applied, source_tables, metric_version}
$ curl -X POST :8000/tools/query_metric -d '{"metric":"active_customers","dimensions":["category"]}'
HTTP 422 dimension_not_allowed, allowed_dimensions ["region","segment"]
$ curl -X POST :8000/tools/execute_sql -d '{"sql":"DROP TABLE fact_orders"}'
HTTP 404 unknown_tool

$ curl :8001/health                                            -> "gemini":"configured","gemini_model":"scripted-model"
$ curl -X POST :8001/chat -d '{"question":"Qual região teve a maior receita?","session_id":"demo-1"}'
HTTP 200 "status":"ok","answer":"[roteiro falso, não é o Gemini] A região com maior receita líquida é Sudeste, com R$ 13063627.23 (métrica net_revenue, query_id f17eb739-...)."
 tool_calls: list_metrics (rodada 1) -> query_metric net_revenue por região, desc, limit 1 (rodada 2) -> show_sql (rodada 3), todas ok
 queries[0]: rows [{"region":"Sudeste","value":"13063627.23"}], sql "SELECT dr.region_name AS \"region\", ... ORDER BY \"value\" DESC NULLS LAST, \"region\" ASC LIMIT ?", sql_params [2],
             source duckdb:analytics.duckdb, etl_run_id 2, rules {denominator, status_rule, time_basis}, cosmos_decision_id authz_68640a08...
Chave falsa nos logs da API (logs/api.log): ausente. Chave do ambiente em logs/*.log e nos logs do uvicorn: ausente.
```
O valor 13063627.23 do Sudeste é igual ao do golden `net_revenue.by_region`, calculado por SQL independente no PostgreSQL.

### Testes
```
$ make test            # .venv/bin/python -m pytest -m "not live_gemini" -q
241 passed, 14 deselected in 55.94s      # 174 das fases 2 e 3 + 67 desta fase
$ GEMINI_API_KEY= .venv/bin/python -m pytest -m live_gemini -q -rs
SKIPPED [14] tests/live/test_live_gemini.py:32: GEMINI_API_KEY ausente
14 skipped, 241 deselected
```
Novos arquivos e o que cobrem:
- `unit/test_gemini_declarations.py` (5): são exatamente 7 `FunctionDeclaration`, iguais a `agent_capabilities.yaml`; nenhum parâmetro de SQL ou tabela; `automatic_function_calling.disable is True`; temperatura 0; o corpo HTTP que o SDK real serializa tem as 7 declarações e a instrução de sistema.
- `unit/test_gemini_errors.py` (14): instâncias reais de `google.genai.errors.ClientError` e `ServerError` mapeadas (401, 403, 404, 429, 500, 503 e 400 de chave inválida); 429 e 5xx com novas tentativas de 1 s e 2 s; desistência após 2 novas tentativas; 401 e 404 sem nova tentativa; mensagem de erro sem a chave; resposta bloqueada detectada.
- `integration/test_api.py` (12): `/health` sem Gemini; `/chat` e `/ask` sem chave devolvem 503; catálogo, dimensões e glossário; cada `/tools` grava `audit.query_audit` com `cosmos_decision_id` igual ao `decision_id` do evento `runtime.authorization.decision` no SQLite do Cosmos, com 1 decisão e 1 `runtime.adapter.result`, episódio `completed` e `pending` vazio; falha de esquema sem decisão e sem episódio; falha de domínio com 1 decisão e 1 resultado; códigos 400, 403, 404, 409, 413, 422, 500 e 503; usuário B não lê `query_id` de A; capacidade removida do grafo nega a ferramenta (1 decisão, 0 resultados) e a reposição volta a permitir; grafo ilegível nega tudo; grafo sem `poc.metric` dá 503; `/health` responde em menos de 1 s durante uma consulta de 1,5 s.
- `integration/test_orchestration.py` (14), com o SDK real e o transporte roteirizado, **não é o Gemini**: loop `search_concepts → query_metric → show_sql → texto` com o número igual ao golden, 3 decisões e 3 resultados no Cosmos no mesmo episódio, `chat_turn` `ok` e episódio `completed`; o resultado de `query_metric` enviado ao modelo não contém SQL; histórico da sessão enviado na pergunta seguinte; `unknown_metric` e `dimension_not_allowed` voltam ao modelo; pergunta ambígua devolve as duas métricas; chamadas paralelas na mesma rodada; limite de 6 rodadas dá `incomplete`; resposta bloqueada; 401 e 404 dão 503 com `chat_turn` `error` e episódio `failed`; 503 repetido dá 502; teste de log em que o servidor devolve a chave na mensagem de erro e `logs/api.log` não a contém.
- `integration/test_questions_golden.py` (21): 19 perguntas via `POST /tools/{name}`, comparadas com `expected.json` (tolerância 0 em dinheiro e contagens, 1e-9 em razões), seguidas de `show_sql` e `get_evidence` para o mesmo `query_id`. Erros esperados com HTTP 422, evidência `rejected` e `show_sql` 409. Depois da tentativa de injeção, `order_count` continua 20000. Esses testes validam os números do Query Engine, **não** a escolha de ferramenta do Gemini.
- `live/test_live_gemini.py` (14, marcador `live_gemini`): as perguntas com número esperado, de ponta a ponta via `/chat` com o Gemini real. Ficam em skip sem `GEMINI_API_KEY`.

### Critérios de aceite
- **7** (respostas numéricas iguais às queries de referência): verificado por execução no nível do Query Engine e da API (19 perguntas e 63 casos golden).
- **8** (SQL inspecionável): verificado por execução (`show_sql`, `queries[].sql` em `/chat`, `audit.query_audit.sql_text`).
- **9** (evidências disponíveis): verificado por execução (`get_evidence`, `GET /evidence/{id}`, `cosmos_decision_id` conferido contra o SQLite do Cosmos).
- **5** (Gemini conectado) e **6** (o agente descobre conceitos e consulta métricas): **implementado até a fronteira HTTP do SDK, não verificado ao vivo.**

### O que NÃO foi verificado ao vivo
- Nenhuma chamada ao Gemini real foi validada. Todos os testes de chat e o servidor da porta 8001 usam um transporte roteirizado, e as respostas desses testes foram escritas pelo roteiro, não pelo Gemini.
- Não foi verificado que o Gemini real escolhe as ferramentas certas, preenche os argumentos certos, respeita a instrução de sistema ou responde em português. Também não foi verificado que o nome `gemini-2.5-flash` é aceito pela API.
- Formato real de resposta bloqueada e de erros de autenticação: o mapeamento segue o formato de `google.genai.errors`, testado com respostas HTTP montadas à mão.
- Divergência de ambiente: o enunciado diz que `GEMINI_API_KEY` não está definida, mas o shell e o `.env` têm um valor de 53 caracteres (não registrado aqui). Durante o desenvolvimento, uma chamada acidental de `/chat` com esse valor recebeu HTTP 402 do serviço e a API respondeu 502 `llm_unavailable`. Depois disso, toda execução usou `GEMINI_API_KEY=` ou chave falsa nos fixtures, e `pytest -m live_gemini` não foi rodado com o valor. Validar 5 e 6 exige rodar `pytest -m live_gemini` com uma chave válida.
- Endpoints de leitura do plano 4.3 para o frontend (`/quality/*`, `/etl/runs`, `/audit/queries`, `/overview`) não foram feitos nesta etapa. O escopo pedido foi chat/ask, catálogo, glossário, health e evidência. Ficam para a Fase 5.
- O 504 `query_timeout` pela API não tem teste próprio. O timeout real com `interrupt()` está provado no Query Engine (Fase 3), e a API só repassa o código pela tabela `HTTP_STATUS`.
- Docker continua indisponível.

Nada foi commitado nesta etapa, conforme instrução.

## Fase 5: Frontend Streamlit e Docker Compose
### O que foi feito
- API: novo `app/api/routes_read.py` com `GET /etl/runs`, `/quality/runs`, `/quality/results`, `/audit/queries`, `/audit/queries/{id}` e `/overview`. Qualidade e cargas leem `ops.*` e a auditoria lê `audit.query_audit`, todas com o papel `poc_app` (só SELECT). `/overview` chama o `ToolExecutor` (Cosmos + Query Engine + auditoria) sob o usuário interno `overview`, para não poluir a lista de auditoria do usuário. Nenhum endpoint existente mudou.
- Frontend (`app/frontend/`, só HTTP via `httpx`, nunca banco nem Gemini): `Home.py` e 5 páginas (`1_Analytics_Assistant`, `2_Semantic_Catalog`, `3_Data_Quality`, `4_SQL_and_Evidence`, `5_Data_Overview`), mais `api_client`, `formatting` (BRL/percentual pt-BR a partir de `Decimal`), `charts` (Plotly), `theme`, `components`. Tema em `.streamlit/config.toml`.
- Assistente: chat com exemplos clicáveis; resposta, indicadores, gráfico e expanders de métrica/regras/filtros, SQL executado e evidências (fonte, versão, episódio e decisão do Cosmos). Sem chave: aviso claro e aba "Consulta direta de métrica" (`/tools/query_metric`), que funciona sem Gemini. Páginas 2 a 5 não dependem da chave.
- Docker (NÃO executado): `Dockerfile` (python:3.11-slim, usuário não root, Cosmos no commit fixado em `/opt/cosmos`, sem `pgserver`), `docker-compose.yml` (`postgres:16.2`, `init` com perfil `init`, `api` com 1 worker, `frontend`; healthchecks; volumes `pg_data`, `duckdb_data` em `/data`, `cosmos_world` em `/world`; segredos mínimos por serviço), `.dockerignore`, `scripts/docker_init.sh`, `scripts/cosmos_world_init.sh`.
### Validação por execução real
```
$ .venv/bin/python -m pytest tests/frontend tests/unit/test_compose_static.py -q
25 passed in 8.74s
$ .venv/bin/python -m pytest tests -q -m "not live_gemini"
266 passed, 14 deselected in 48.85s        # 241 anteriores + 25 desta fase
```
- `tests/frontend/test_pages_apptest.py`: `AppTest.from_file` sobre uvicorn real (subprocesso, bancos e World do Cosmos reais, `GEMINI_API_KEY` vazia). Cada página roda sem exceção; as 8 métricas aparecem no catálogo; KPIs do Overview iguais ao golden (`expected.json`); Qualidade mostra regras e cargas; SQL & Evidence lista a chamada auditada e mostra SQL e decisão do Cosmos; Assistente sem chave mostra o aviso, sem campo de chat, e a consulta direta devolve o valor do Sudeste igual ao golden; API fora do ar mostra erro sem exceção; as páginas não importam banco nem Gemini.
- Chat: um teste usa a API com o SDK real e **transporte roteirizado** (`tests/support/serve_fake_gemini.py`). Isso exercita a interface, **não verifica o Gemini**.
- Serviço real (executado): uvicorn e `streamlit run app/frontend/Home.py --server.port 8501 --server.headless true`:
```
http://localhost:8000/health 200 {"status":"ok","gemini":"not_configured",...,"etl_run_id":2}
http://localhost:8501/_stcore/health 200 ok
GET / 200
Home.py exceptions: 0 ... pages/1..5: exceptions: 0 (Assistente com aviso de chave; Overview com 6 métricas)
```
  Processos encerrados depois. Também executado de verdade: `scripts/cosmos_world_init.sh` em diretório temporário (cria o World, segunda execução é no-op), seguido de `python -m semantic.sync_to_cosmos` e `cosmos validate` (`valid: true`).
### Docker: NÃO executado
`docker` e `hadolint` não existem aqui. `tests/unit/test_compose_static.py` (11 testes) só lê os arquivos: YAML válido; serviços e perfil; toda variável `${...}` existe em `.env.example`; nomes de ambiente são campos de `Settings`; API sem senhas além de `PG_APP_PASSWORD`, frontend sem segredos; portas, comandos, healthchecks, `depends_on`, volumes e caminhos montados coerentes; módulos do `docker_init.sh` existem; revisão do Dockerfile no estilo hadolint (base fixa, `--no-install-recommends`, limpeza do apt, sem cache do pip, usuário não root, sem segredos em ENV, `COPY` existentes, commit do Cosmos igual ao de `bootstrap.sh`). `docker compose config`, `docker build` e a subida dos contêineres **não foram verificados**, nem o encaixe do World no volume.
### Não verificado
- Chat com o Gemini real (sem chave); `gemini-2.5-flash` não validado.
- Aparência visual: há Google Chrome, mas a captura headless mostrou só o esqueleto de carregamento (WebSocket não concluiu). A captura foi descartada; a interface não foi vista em navegador.
- Docker e compose (acima). A API em contêiner reinicia (`on-failure`) até o `init` criar World e DuckDB.
- Uso: `cp .env.example .env`, `docker compose up -d postgres`, `docker compose run --rm init`, `docker compose up -d api frontend`.
Nada foi commitado, conforme instrução.
## Fase 6: Validação, README e relatório de aceite
### O que foi feito
- `README.md` em pt-BR (visão geral, arquitetura e relação Cosmos/Gemini/bancos, configuração, execução com e sem Docker, ETL/API/UI/testes, perguntas de exemplo, limitações).
- `docs/ACCEPTANCE_REPORT.md` com os 12 critérios, cada um como "verificado por execução" (comando e trecho de saída) ou "não verificado" (motivo).
- Nenhum código de produto mudou. Nada foi commitado, conforme instrução.
### Comandos executados (todos com `GEMINI_API_KEY=` vazia; o valor do ambiente não foi usado)
```
$ .venv/bin/python scripts/pg_local.py stop
$ mv pgdata analytics.duckdb dq_lab.duckdb logs .cosmos cosmos.environment.json /tmp/poc-backup-1795368000/   # estado limpo, sem apagar
$ make GEMINI_API_KEY= pg-start migrate load       # 5000/500/20/5/20000/47617/20000/7194 linhas
$ make GEMINI_API_KEY= etl                         # ETL 1 concluído em 252 ms, 8 tabelas
$ make GEMINI_API_KEY= quality                     # oltp: 0 violações, 8 reconciliações OK; dq_lab: 7 regras DETECTADO; "qualidade: TUDO OK"
$ .venv/bin/cosmos init . && rm -rf .githooks
$ make GEMINI_API_KEY= sync                        # 103 registros, validate_graph_errors []; cosmos validate: valid true
$ make GEMINI_API_KEY= metric-tests                # 21/21 testes de métrica passaram
$ make GEMINI_API_KEY= load                        # segunda carga: "linhas novas inseridas em oltp: 0"
$ make GEMINI_API_KEY= golden                      # valores iguais aos versionados (só a ordem das linhas muda); arquivo restaurado com git checkout
$ make GEMINI_API_KEY= test                        # 266 passed, 14 deselected in 45.66s
$ GEMINI_API_KEY= .venv/bin/python -m pytest -m live_gemini -q -rs   # 14 skipped (GEMINI_API_KEY ausente)
$ .venv/bin/python -m pytest tests/frontend -q     # 14 passed (AppTest)
$ bash scripts/bootstrap.sh                        # "Checked 18 packages", "Bootstrap concluído"
$ uvicorn app.api.main:app (porta 8000) e streamlit run app/frontend/Home.py (porta 8501, headless)
$ curl :8000/health                                # 200 gemini not_configured, postgres/duckdb/cosmos ok, etl_run_id 1
$ curl -X POST :8000/ask                           # 503 gemini_not_configured
$ curl -X POST :8000/tools/query_metric net_revenue 2026-10-02..2026-10-31   # 200 876344.70 (= golden)
$ curl -X POST :8000/tools/query_metric active_customers por category         # 422 dimension_not_allowed
$ curl -X POST :8000/tools/query_metric metric=lucro                           # 422 unknown_metric
$ curl -X POST :8000/tools/execute_sql                                         # 404 unknown_tool
$ curl -X POST :8000/tools/query_metric net_revenue por region top 1           # Sudeste 13063627.23 (= golden)
$ curl -X POST :8000/tools/show_sql ; curl :8000/evidence/<id>                 # 200
$ curl :8000/overview ; :8000/quality/runs ; :8501/_stcore/health ; :8501/     # 200
$ grep -c AIza logs/*.log                          # 0 ocorrências
```
Servidores encerrados ao final. O PostgreSQL local ficou ligado.
### Não verificado
Gemini real, Docker/Compose, interface em navegador, instalação em clone limpo. Detalhes e motivos em `docs/ACCEPTANCE_REPORT.md`.
