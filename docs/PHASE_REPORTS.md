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
