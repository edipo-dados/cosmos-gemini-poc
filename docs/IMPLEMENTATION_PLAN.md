# Implementation Plan (Fases 2 a 6)

Base: `docs/TASK.md` (seção 14 e 12 critérios de aceite), `docs/ARCHITECTURE.md` (decisões aprovadas, não reabrir), `docs/ENV_CHECK.md`, `docs/COSMOS_DISCOVERY.md`.

## 0. Convenções válidas para todas as fases

- Python: `/Users/edipo/projetos/poc-cosmos/.venv/bin/python` (3.11.18). Comandos abaixo usam `PY=.venv/bin/python`. Sem Docker: PostgreSQL 16.2 real via `scripts/pg_local.py start|stop` (pgserver, TCP porta 54329, dados em `pgdata/`, ignorado pelo git). Nunca mockar Postgres, DuckDB ou Cosmos nos testes de aceite.
- Código e identificadores em inglês; docs e README em pt-BR. Segredos só por env. `.env`, `pgdata/`, `logs/`, `*.duckdb`, `.cosmos/`, `cosmos.environment.json`, `.githooks/` vão no `.gitignore` (acrescentar o que faltar na fase que o cria). `.agents/` já está ignorado: não forçar `git add -f`.
- Cada fase termina com: suíte da fase verde, saída colada em `docs/PHASE_REPORTS.md` (comando, saída, critérios fechados, itens NÃO verificados) e commit local `feat(phaseN): ...`. Nunca `git push`.
- Os nomes `tools/` e `runtime/` não podem existir na raiz (ocupados pelo `cosmos-platform`); `agent/tools` é seguro. Teste `tests/unit/test_no_toplevel_name_clash.py` (Fase 2).
- Config central: `app/config.py` (pydantic-settings) lê `PG_HOST/PORT`, `PG_*_PASSWORD` (admin, loader, reader, dq, app), `DUCKDB_PATH`, `DQ_LAB_DUCKDB_PATH`, `SEED` (42), `DATA_END_DATE` (2026-10-31), `COSMOS_WORLD_DIR`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `API_URL`. `.env.example` com placeholders. Filtro de logging `app/logging_setup.py` redige chave e senhas.
- Marcadores pytest em `pytest.ini`: `live_gemini` (skip sem chave), `slow`. `tests/conftest.py` fornece fixtures de sessão: `pg_server` (sobe pgserver, aplica migrações, gera dados, roda ETL em diretório temporário, uma vez por sessão) e `duckdb_path`. Testes de integração usam esses bancos reais; testes rápidos de unidade não precisam deles.
- Ordem das dependências entre fases: 2 → 3 → 4 → 5 → 6. Dentro de cada fase, os itens estão ordenados por dependência; cada item deixa o repositório compilável e `pytest` coletável.

### Mapa de critérios de aceite

| Critério | Fecha na fase | Observação |
|---|---|---|
| 1 Postgres populado | 2 | execução real |
| 2 DuckDB populado | 2 | execução real |
| 3 Pipeline de carga | 2 | execução real, com logs |
| 4 Cosmos inicializado e integrado | 3 | `cosmos validate`, sync, MCP, gateway |
| 7 Números = SQL de referência | 3 (motor) e 4 (15 perguntas via `/tools`) | valida o Query Engine, não a escolha de ferramenta do Gemini |
| 8 SQL inspecionável | 4 | `show_sql` via API |
| 9 Evidências | 4 | `get_evidence` via API |
| 5 Gemini conectado, 6 Agente descobre conceitos | 4 (implementado até a fronteira) | **não verificados ao vivo** sem `GEMINI_API_KEY`; só 6 parcial: `search_concepts`/`explain_metric` verificados via `/tools` |
| 10 Interface funcional | 5 | AppTest + serviço Streamlit real + API real |
| 11 Testes passando | 6 | suíte completa |
| 12 Inicia seguindo o README | 6 | seguir o README literalmente em clone limpo, sem Docker; Docker declarado não verificado |

---

## Fase 2: Data Foundation (critérios 1, 2, 3)

### Layout de módulos

```
requirements.txt  requirements-dev.txt(opcional)  pytest.ini  Makefile  .env.example
scripts/bootstrap.sh            # uv pip install -r requirements.txt; clona Cosmos no commit fixado; cosmos init se ausente (usado na Fase 3)
scripts/pg_local.py             # start|stop|status pgserver, porta 54329
app/config.py  app/logging_setup.py  app/db.py   # engines SQLAlchemy por papel
database/migrations/            # 001_roles_schemas.sql 002_oltp.sql 003_dq_lab.sql 004_audit.sql 005_ops.sql 006_grants.sql ; runner database/migrate.py
database/postgres/init/         # mesmos SQL de papéis para o compose
data/generators/{__init__,config,reference,customers,products,orders,refunds,defects,run}.py
pipelines/extract/postgres_extract.py
pipelines/transform/{schema.py,build_duckdb.py,run.py}
pipelines/quality/{run.py,runner.py,reconcile.py,rules/*.sql,reference_sql/*.sql}
tests/{conftest.py,unit,integration,security,golden}
```

### Itens

- [ ] 2.1 Dependências e ambiente. Criar `requirements.txt` com as versões da seção 12 do ARCHITECTURE, instalar com `uv pip install --python .venv/bin/python -r requirements.txt` (uv em `~/Library/Python/3.9/bin`), e corrigir qualquer pin que falhe (registrar a troca em `PHASE_REPORTS.md`); gerar `requirements.lock.txt` com `uv pip compile`. Criar `pytest.ini`, `.env.example`, `.gitignore` atualizado, `scripts/pg_local.py`, `app/config.py`, `app/logging_setup.py`.
  Verify: `PY scripts/pg_local.py start && PY -c "import duckdb,fastapi,streamlit,google.genai,faker,sqlalchemy,psycopg;print('ok')"`; `PY -m pytest tests/unit -q` (teste do filtro de log redigindo chave e do `test_no_toplevel_name_clash`).

- [ ] 2.2 Migrações PostgreSQL (depende de 2.1). `database/migrate.py` aplica `database/migrations/*.sql` em ordem como `poc_admin`, registra versões em `ops.schema_migrations`, idempotente. Criar banco `analytics_poc`, schemas `oltp`, `dq_lab`, `audit`, `ops`, papéis `poc_admin/loader/reader/dq/app` conforme seção 8 (senhas vindas de env, nunca no SQL versionado: o runner faz `ALTER ROLE ... PASSWORD` por parâmetro). `oltp`: `categories, regions, customers, products, orders, order_items, payments, refunds` com PKs, FKs, UNIQUE (`payments.order_id`, `refunds.order_item_id`), CHECKs (valores ≥ 0, status em conjuntos fixos, `refund_amount <= ...` quando expressável), índices em FKs e `orders(order_date)`, `orders(status)`. `dq_lab`: mesmas tabelas sem FKs/CHECKs. `audit.chat_turn`, `audit.query_audit` com triggers e GRANTs de coluna da seção 9. `ops.etl_run`, `ops.dq_run`, `ops.dq_result`, `ops.schema_migrations`.
  Files: `database/migrate.py`, `database/migrations/*.sql`, `database/postgres/init/*`.
  Verify: `PY -m database.migrate` duas vezes (segunda sem mudança); `PY -m pytest tests/integration/test_migrations.py tests/security/test_pg_permissions.py -q`. O teste de segurança prova com conexões reais: `poc_reader` falha em `INSERT oltp.customers` e em `SELECT dq_lab.*`; `poc_app` falha em `UPDATE/DELETE audit.query_audit`, `DELETE audit.*`, `UPDATE audit.chat_turn SET question=...` e na transição `ok→error`; transição `started→ok` funciona; FK `query_audit.turn_id` existe.

- [ ] 2.3 Geradores determinísticos (depende de 2.2). Faker `pt_BR` com `Faker.seed(seed)` e `random.Random(seed)`; sem dados pessoais reais (CPF gerado só se necessário e marcado sintético; preferir não gerar). Volumes: 5.000 clientes, 500 produtos, 20 categorias, 5 regiões, 20.000 pedidos, ≥ 35.000 itens, 20.000 pagamentos (1 por pedido), reembolsos > 0, 24 meses terminando em `DATA_END_DATE`. Segmentos (3 a 4), 4 formas de pagamento, status `pending/paid/cancelled/refunded`, regras da seção 6 (pagamento `captured/pending/voided`, reembolso por item `completed/pending/rejected`, reembolso ≤ total do item, `refunded` só se todos os itens reembolsados integralmente). Padrões variados: sazonalidade mensal, clientes com frequência distinta, categorias com preços distintos. Carga idempotente: IDs determinísticos e `INSERT ... ON CONFLICT DO NOTHING` em lotes via `poc_loader`; guarda `ops.generator_state(seed, params_hash)`: mesmo seed reexecutado insere 0 linhas; seed diferente sem `--reset` sai com código 2; `--reset` faz `TRUNCATE` e recarrega. `defects.py` popula `dq_lab` (nunca `oltp`) com defeitos determinísticos (seção 10) e grava `tests/golden/dq_expected.json`. CLI: `python -m data.generators.run --seed 42 [--reset]`.
  Verify: `PY -m data.generators.run --seed 42` (contagens impressas = alvo); repetir (0 novas); `--seed 7` sem `--reset` → exit 2; `PY -m pytest tests/unit/test_generators.py tests/integration/test_load_idempotent.py -q` (mesmo seed gera DataFrames idênticos; contagens reais lidas do PostgreSQL por SQL; todos os status e métodos presentes; 24 meses cobertos; `oltp` sem nenhum defeito).

- [ ] 2.4 ETL PostgreSQL → DuckDB (depende de 2.3). `pipelines/extract/postgres_extract.py` com lista fixa de tabelas `oltp.*` e conexão `poc_reader` (read-only). `pipelines/transform/build_duckdb.py` constrói em arquivo temporário `analytics.duckdb.tmp`: `dim_customer, dim_product, dim_region, dim_date, fact_orders, fact_order_items, fact_payments, fact_refunds` (dim_product com categoria denormalizada, `DECIMAL(12,2)`), `etl_meta(etl_run_id, finished_at, source_row_counts)`; antes da troca roda as verificações de qualidade em `oltp` (Fase 2.5, função importada) e aborta sem trocar o arquivo se houver violação; troca por `os.replace`. `etl_run_id` vem de `ops.etl_run` (gravado com `poc_loader`, status `running→success|failed`). Logs em `logs/etl.log` (arquivo + console, contagens por tabela, duração). Reexecução recria o arquivo de forma reprodutível. CLI: `python -m pipelines.transform.run`.
  Verify: `PY -m pipelines.transform.run`; `PY -m pytest tests/integration/test_etl.py -q`: as 8 tabelas existem e contagens batem com `oltp` por SQL no PostgreSQL; `etl_meta.etl_run_id` = `ops.etl_run.id`; segundo ETL muda `etl_run_id` e preserva o conteúdo; ETL com defeito injetado em tabela temporária de `oltp` aborta e deixa o arquivo anterior intacto; inspeção do SQL de extração só referencia `oltp.`.

- [ ] 2.5 Qualidade e reconciliação (depende de 2.4; 2.4 importa a função de verificação, então implementar `pipelines/quality/runner.py` e as regras antes de ligar o abort do ETL). Regras em `pipelines/quality/rules/*.sql` (1 arquivo por regra, retorna as linhas violadoras): `orders_without_customer`, `items_without_product`, `duplicate_payments`, `cancelled_with_captured_payment`, `refund_exceeds_paid`, `negative_values`, `inconsistent_dates`. `pipelines/quality/reference_sql/*.sql` (8 arquivos, um por métrica, escritos à mão contra `oltp`, independentes do Query Engine). `reconcile.py` compara valor de referência (PostgreSQL) com valor lido de `analytics.duckdb`: tolerância 0 para dinheiro e contagens, 1e-9 para razões; defeito de divergência demonstrado com `dq_lab.duckdb` (arquivo à parte, nunca aberto pela API). Resultados em `ops.dq_run`/`ops.dq_result` via `poc_dq`. CLI: `python -m pipelines.quality.run`.
  Verify: `PY -m pipelines.quality.run` (0 violações em `oltp`, contagens do manifesto em `dq_lab`, 8/8 reconciliadas); `PY -m pytest tests/integration/test_quality.py tests/integration/test_isolation.py -q`: contagem por regra em `dq_lab` = `tests/golden/dq_expected.json`; `oltp` = 0; contagem das métricas em `analytics.duckdb` não muda depois de recarregar `dq_lab`; divergência `dq_lab` x `dq_lab.duckdb` é detectada.

- [ ] 2.6 Fechar a fase. Criar `Makefile` (`make pg-start migrate load etl quality test`), `scripts/bootstrap.sh` parcial (sem Cosmos ainda: só instalação), e `docs/PHASE_REPORTS.md` seção Fase 2 com saídas reais.
  Verify: `PY -m pytest tests/unit tests/integration tests/security -q` verde; pipeline completo do zero (`pg_local stop`, apagar `pgdata/` e `analytics.duckdb`, rodar `make` alvos em ordem) funciona.

**Fecha:** critérios 1, 2, 3. **Não verificado:** Docker (compose escrito só na Fase 5).

**Gate do revisor da fase 2** (`phase2-review.json`): lê o diff, reexecuta a suíte, confere critérios 1 a 3 por SQL direto contra PostgreSQL e DuckDB, volumes, idempotência, permissões e isolamento.

---

## Fase 3: Semantic Governance e Query Engine (critério 4; critério 7 no nível do motor)

### Layout

```
semantic/metrics/*.yaml (8)  semantic/dimensions/*.yaml (9)  semantic/rules/*.yaml  semantic/rules/agent_capabilities.yaml
semantic/glossary/glossary.yaml  semantic/schema/*.json  semantic/loader.py  semantic/sync_to_cosmos.py
app/services/query_engine/{validation.py,catalog.py,sql_builder.py,executor.py,service.py,errors.py}
app/services/audit.py  app/services/semantic_reader.py
agent/tools/{schemas.py,executor.py,handlers.py,registry.py,cosmos_gateway.py}   # ToolExecutor, provider, ToolAdapter
scripts/{compute_golden.py,cosmos_world_init.sh}
cosmos/documentation/USO_DO_COSMOS.md
tests/{unit,integration,security,golden}
```

### Itens

- [ ] 3.1 Cosmos World e bootstrap (depende da Fase 2). Completar `scripts/bootstrap.sh`: clonar `https://github.com/cosmos-semantic/cosmos` no commit `464175f6bfa641c30f0b2cdeb0ef84269fd202cb` em `.vendor/cosmos` se ausente, `pip install -e`, rodar `cosmos init .` se `cosmos.environment.json` não existir, remover `.githooks/`. Ajustar `.gitignore`. Escrever `scripts/cosmos_world_init.sh` (container, não verificável).
  Verify: `.venv/bin/cosmos validate .` retorna `valid: true`; `PY -c "import tools.validate_ontology, runtime.cosmos_runtime"`; reexecutar bootstrap é no-op.

- [ ] 3.2 Catálogo YAML e loader. Criar os YAML conforme TASK seção 6 e ARCHITECTURE seção 6: 8 métricas (campos: `name, business_name, description, formula, source, expression, base_filter, joins, allowed_dimensions, applicable_filters, owner, version, tests`), 9 dimensões, regras (denominadores, status, janelas), glossário pt-BR com sinônimos (faturamento, receita, ticket médio, cliente ativo, cancelamento...), `agent_capabilities.yaml` com as 7 ferramentas. Esquemas JSON em `semantic/schema/`. `semantic/loader.py` valida com `jsonschema` e calcula `catalog_version` (hash).
  Verify: `PY -m pytest tests/unit/test_semantic_catalog.py -q`: esquema válido; matriz métrica × dimensão do YAML igual à tabela da seção 6; todas as métricas têm owner, version e testes; "receita" mapeia para as duas métricas candidatas.

- [ ] 3.3 Sync para o Cosmos (depende de 3.1 e 3.2). `semantic/sync_to_cosmos.py` conforme 5.2: valida YAML, monta registros com `extensions["poc.sync"].owner = "semantic-sync"`, IDs por `stable_cosmos_ref`, nós `actor` (`poc.agent`, `poc.user`), `poc.metric`, `poc.dimension`, `poc.glossary_term`, `knowledge` rule, arestas `core.governed_by`, nós `capability` com `resources=[{system:"poc-tools", uri:"tool:<nome>"}]`; remove registros próprios antigos; `validate_graph`; escrita atômica; sai com código 2 `world_not_initialized` se o World faltar.
  Verify: `PY semantic/sync_to_cosmos.py` duas vezes (grafo idêntico); `PY -m pytest tests/integration/test_cosmos_sync.py -q`: MCP em subprocesso (`COSMOS_GRAPH` absoluto e `cwd` fixos, `count > 0`), 8 métricas/9 dimensões/regras/sinônimos presentes com mesmos textos e versões via `cosmos_query where id` e `cosmos_explain` (lista regras por `core.governed_by`); alterar YAML em diretório temporário muda o grafo; remover ferramenta do YAML remove o nó (sem órfãos) e o gateway nega; `validate_graph == []` e `cosmos validate` `valid: true`.

- [ ] 3.4 Query Engine (depende de 3.2 e Fase 2). `validation.py` (Pydantic, `extra="forbid"`, regras da tabela da seção 6), `catalog.py`, `sql_builder.py` (SQL parametrizado com `?`, identificadores só do YAML, checagem `SELECT/WITH` única, `monthly_revenue_growth` com calendário completo e `LAG` antes do filtro de data, `active_customers` com `as_of=date_to` e janela `[as_of-89, as_of]`), `executor.py` (conexão `read_only=True` por requisição, lê `etl_meta`, cache categórico por `etl_run_id`, timeout 10 s com `interrupt()`, corte 1000 linhas), `service.py` (devolve linhas, `filters_applied`, `etl_run_id`, `catalog_version`, SQL, evidência com regras e denominador). Erros em `errors.py` com os códigos da seção 6.1.
  Verify: `PY -m pytest tests/unit/test_validation.py tests/unit/test_sql_builder.py tests/integration/test_query_engine.py -q`: SQL injection em filtros e dimensões (parâmetros, nada vaza para o SQL); dimensão não autorizada (`active_customers` com `category`); métrica inexistente; limites; `active_customers` com `date_to` e com `date_from` (rejeitado); `monthly_revenue_growth` com janela, `order_by`, `limit`; timeout real com consulta `range(1e10)` em conexão `read_only` (se `interrupt()` falhar, registrar em PHASE_REPORTS e trocar por thread com `duckdb` close; decidir pela execução); dois ETLs sem reiniciar mudam `etl_run_id` e valores categóricos.

- [ ] 3.5 Golden das métricas (depende de 3.4, pode rodar em paralelo mental com 3.6). `scripts/compute_golden.py` roda SQL independente no PostgreSQL (`oltp`, via `poc_reader`) e grava `tests/golden/expected.json` com os números esperados por métrica e por recorte (região, mês, categoria, método). Teste de reconciliação compara com o Query Engine.
  Verify: `PY scripts/compute_golden.py` e `PY -m pytest tests/integration/test_metrics_reconciliation.py -q`: 8/8 métricas e cortes por região/mês/categoria iguais (tolerância 0 em dinheiro e contagens).

- [ ] 3.6 Adaptador de ferramentas e gateway Cosmos (depende de 3.3, 3.4). `agent/tools/schemas.py` (Pydantic por ferramenta, `extra="forbid"`), `semantic_reader.py` (caminho explícito, cache por mtime, `semantic_catalog_unavailable`), `cosmos_gateway.py` (`build_services`, `ToolAdapter` com 7 handlers que só fazem `pending.pop`, `AuthorizationGateway` com provider que lê os nós `capability`, fail closed), `executor.py` (`ToolExecutor`: esquema → `new_attempt/authorize` sob lock curto → domínio fora do lock → `ToolAdapter.execute` sob lock curto → auditoria em `finally`), `app/services/audit.py` (grava `audit.chat_turn` e `audit.query_audit` via `poc_app`), `handlers.py` (7 ferramentas), com `READY → RUNNING → COMPLETED/FAILED` por episódio.
  Verify: `PY -m pytest tests/integration/test_cosmos_contract.py tests/integration/test_tool_executor.py -q`: provider sobre grafo real; duas chamadas idênticas geram dois episódios e duas decisões `allow`; `intake created=False` tratado como erro; `invalid_arguments` (`query_id="abc"`, `query=""`, `metric="X-1"`) → 0 decisões, 0 `adapter.result`, linha `rejected` com `cosmos_decision_id` nulo; `unknown_metric` → 1 decisão + 1 `adapter.result`; ferramenta negada → 1 decisão `deny` e motor não chamado; `semantic_catalog_unavailable` (grafo ausente, ilegível, sem `poc.metric`); `explain_metric` com ID ausente → `internal_error`; falha de auditoria → `audit_failed`; `pending` vazio no final; posse de `query_id` por `user_id`.

- [ ] 3.7 Fechar a fase. Documento `cosmos/documentation/USO_DO_COSMOS.md` (relação YAML ↔ Cosmos, limites, tabela proven/unproven atualizada), seção Fase 3 em `PHASE_REPORTS.md` incluindo "comportamento do `SemanticReader` e de `explain_metric` sobre o grafo do sync real: verificado/não verificado" com saídas.
  Verify: `PY -m pytest tests -q -m "not live_gemini"` verde; `PY semantic/sync_to_cosmos.py && .venv/bin/cosmos validate .`.

**Fecha:** critério 4; critério 7 no nível do Query Engine (8 métricas contra SQL de referência). **Não verificado:** admissão oficial de conhecimento do Cosmos (sync grava `active` direto, declarado).

**Gate do revisor da fase 3** (`phase3-review.json`): reexecuta sync e testes, checa que o Query Engine lê YAML e não o grafo, que nenhum texto do usuário entra no SQL, que `read_only=True`, e que cada afirmação sobre o Cosmos tem execução.

---

## Fase 4: Gemini + FastAPI (critérios 7, 8, 9 fechados; 5 e 6 só até a fronteira)

### Layout

```
agent/gemini/{client.py,declarations.py,errors.py,prompts.py}
agent/orchestration/{loop.py,session.py}
app/api/{main.py,schemas.py,deps.py,routes_chat.py,routes_tools.py,routes_data.py,errors.py,lifespan.py}
tests/golden/questions.json  tests/integration/{test_api_*.py,test_questions_golden.py,test_orchestration.py}  tests/live/test_live_gemini.py
```

### Itens

- [ ] 4.1 Ler a API instalada do `google-genai` (`PY -c "import google.genai as g;print(g.__version__)"`, `help(types.FunctionDeclaration)`, `GenerateContentConfig`, `AutomaticFunctionCallingConfig`) e registrar no PHASE_REPORTS o que foi lido. Implementar `agent/gemini/declarations.py` (7 `FunctionDeclaration` geradas a partir dos modelos Pydantic de `agent/tools/schemas.py`), `client.py` (`genai.Client(api_key=...)`, chamada automática desativada, temperatura 0, retries 1 s/2 s para 429/5xx, mapeamento 401/403 → `gemini_auth_failed`, 404 → `gemini_model_invalid`, bloqueio de segurança → `blocked`), `prompts.py` (instrução de sistema pt-BR: não inventar números, citar `query_id`, perguntar em caso ambíguo, usar `explain_metric`).
  Verify: `PY -m pytest tests/unit/test_gemini_declarations.py tests/unit/test_gemini_errors.py -q`: declarações constroem com tipos reais do SDK e cobrem exatamente os 7 nomes; erros do SDK (instanciados a partir de `google.genai.errors`) mapeiam para os códigos certos. Esses testes **não verificam o Gemini**.

- [ ] 4.2 Orquestração. `agent/orchestration/loop.py`: loop manual, máximo 6 iterações, cada `function_call` vai ao `ToolExecutor` (Fase 3), a resposta da função é devolvida ao modelo; `status` `ok|incomplete|blocked|error`; `session.py` mantém histórico em memória (20 turnos). Abre episódio Cosmos por pergunta, grava `audit.chat_turn started → final`. O cliente é injetável via protocolo `LLMClient` para o teste usar um **modelo roteirizado declarado como não-Gemini**.
  Verify: `PY -m pytest tests/integration/test_orchestration.py -q`: roteiro com chamadas `search_concepts → query_metric → show_sql`; métrica inexistente (resposta `unknown_metric` volta ao modelo); dimensão não autorizada; pergunta ambígua ("receita" retorna `search_concepts` com 2 métricas); limite de 6 iterações → `incomplete`; `chat_turn` termina em status final; episódio chega a `COMPLETED`/`FAILED`.

- [ ] 4.3 API FastAPI (depende de 4.2). `app/api/main.py` + `lifespan.py` com os pré-requisitos da seção 5.3 (World, nós actor e capability, `poc.metric`, SQLite do runtime, DuckDB existente; falha → não sobe). Endpoints `def` síncronos: `GET /health` (`status`, `gemini: configured|not_configured`, `postgres`, `duckdb`, `cosmos`, `catalog_version`, `etl_run_id`), `POST /chat`, `POST /tools/{name}`, e leitura para o frontend: `GET /catalog/metrics`, `/catalog/dimensions`, `/catalog/glossary`, `GET /quality/runs`, `/quality/results`, `/etl/runs`, `GET /audit/queries`, `GET /audit/queries/{query_id}`, `GET /overview` (KPIs, série mensal, por região e categoria, via Query Engine, auditado). Validação por Pydantic `extra="forbid"`, limite de corpo 16 KiB (413), cabeçalho `X-User-Id`, tabela de erros da seção 6.1, logs sem chave. `POST /chat` sem chave → 503 `gemini_not_configured`.
  Verify: iniciar `PY -m uvicorn app.api.main:app --port 8000` em segundo plano e `curl -s localhost:8000/health`; `PY -m pytest tests/integration/test_api_tools.py tests/integration/test_api_errors.py tests/integration/test_api_chat_boundary.py -q`: `TestClient`/`httpx` contra bancos reais; um caso por código HTTP da tabela (400, 403, 404, 409, 422, 500, 503, 504); `/health` responde durante consulta lenta; `/chat` sem chave → 503; cada chamada `/tools` cria linha em `audit.query_audit` com `cosmos_decision_id` correto; usuário A não lê `query_id` de B.

- [ ] 4.4 Perguntas golden (depende de 3.5 e 4.3). `tests/golden/questions.json` com ≥ 15 perguntas em pt-BR; cada uma tem `tool_args` esperados e valor calculado por `compute_golden.py` (SQL independente no PostgreSQL). Cobrir as 7 perguntas exemplo do TASK seção 9 (faturamento últimos 30 dias, região com maior receita, categoria com maior ticket médio, clientes ativos, comparação de dois meses, taxa de cancelamento, explicar faturamento líquido) mais ambígua, inexistente (`lucro`), dimensão não autorizada, injeção. `test_questions_golden.py` chama `POST /tools/query_metric` (ou `explain_metric`) e compara com o esperado, depois `POST /tools/show_sql` e `get_evidence` para o mesmo `query_id`. `tests/live/test_live_gemini.py` marcado `live_gemini` roda as mesmas perguntas via `/chat` e compara números; `skip` sem chave.
  Verify: `PY -m pytest tests/integration/test_questions_golden.py -q` (≥ 15 casos verdes); `PY -m pytest -m live_gemini -q` mostra `skipped` com motivo "GEMINI_API_KEY ausente" (nunca passa vazio).

- [ ] 4.5 Fechar a fase. Seção Fase 4 em `PHASE_REPORTS.md`: critérios 7, 8, 9 verificados por execução; critérios 5 e 6 como "implementado até a fronteira, **não verificado ao vivo**", com a lista do que foi provado (declarações, loop roteirizado, erros mapeados, `search_concepts`/`explain_metric` via API).
  Verify: `PY -m pytest tests -q -m "not live_gemini"` verde.

**Fecha:** 7, 8, 9. **Parcial/não verificado:** 5, 6 (sem chave).

**Gate do revisor da fase 4** (`phase4-review.json`): confirma que o Gemini nunca recebe acesso a banco nem SQL livre, que a chamada automática do SDK está desligada, que nenhum teste roteirizado é apresentado como verificação do Gemini, ≥ 15 perguntas, e que a chave não aparece em logs (`grep` apenas como apoio; a prova é o teste de log).

---

## Fase 5: Frontend Streamlit + Docker Compose (critério 10)

### Layout

```
app/frontend/{Home.py,api_client.py,theme.py,formatting.py,charts.py}
app/frontend/pages/{1_Analytics_Assistant.py,2_Semantic_Catalog.py,3_Data_Quality.py,4_SQL_and_Evidence.py,5_Data_Overview.py}
.streamlit/config.toml
Dockerfile  docker-compose.yml  .dockerignore
tests/frontend/{test_pages_apptest.py,test_formatting.py}
```

### Itens

- [ ] 5.1 Cliente HTTP e utilitários. `api_client.py` (`httpx`, `API_URL`, timeout, envio de `X-User-Id`, tratamento de erro do formato `{"error":{...}}`), `formatting.py` (BRL, percentuais, `Decimal` a partir de string), `charts.py` (Plotly), `theme.py` + `.streamlit/config.toml` (identidade visual: paleta sóbria, fonte, cabeçalho). O frontend chama só a API (nunca banco).
  Verify: `PY -m pytest tests/frontend/test_formatting.py -q`.

- [ ] 5.2 Cinco páginas (depende de 5.1 e Fase 4). Assistente: `st.chat_input`, exemplos clicáveis, resposta, indicadores, gráfico, expander com métricas/dimensões/filtros/fonte/evidências; sem chave exibe aviso claro de que o chat está indisponível e oferece o modo "consultar métrica" direto via `/tools/query_metric`. Semantic Catalog (métricas, fórmulas, dimensões, regras, glossário, responsáveis). Data Quality (volumes, regras, violações, histórico de `ops.dq_run`, status de `ops.etl_run`). SQL & Evidence (lista de `audit.query_audit`, SQL com parâmetros, resultado, evidência, ligação Cosmos). Data Overview (KPIs e séries por mês/região/categoria).
  Verify: `PY -m pytest tests/frontend/test_pages_apptest.py -q` com `streamlit.testing.v1.AppTest.from_file` apontando `API_URL` para uma API uvicorn real (fixture sobe `uvicorn` em subprocesso sobre os bancos reais): cada página roda sem exceção, mostra os 8 nomes de métrica, KPIs de Overview iguais ao golden, tabela de auditoria não vazia após uma chamada de `/tools`, e Assistente sem chave mostra o aviso.

- [ ] 5.3 Serviço real. Subir `streamlit run app/frontend/Home.py --server.port 8501 --server.headless true` contra API real e checar `GET /_stcore/health` = `ok`; captura de tela só se houver navegador (checar `which chromium google-chrome`; senão declarar "não verificado visualmente").
  Verify: `curl -s localhost:8501/_stcore/health` retorna `ok` (executado de verdade, processos encerrados depois).

- [ ] 5.4 Docker (não verificável). `Dockerfile` (python:3.11-slim, instala `requirements.txt` e Cosmos no commit fixado em `/opt/cosmos`), `docker-compose.yml` conforme seção 11: `postgres:16.2` com healthcheck e `database/postgres/init`, `init` (perfil `init`), `api` (1 worker, volumes `duckdb_data` e `cosmos_world`, healthcheck `/health`), `frontend` (healthcheck `/_stcore/health`). Validar o YAML com `PY -c "import yaml;yaml.safe_load(open('docker-compose.yml'))"` e comparar nomes de serviços/variáveis com `.env.example` em teste unitário (`tests/unit/test_compose_static.py`). Registrar como NÃO verificado por execução.
  Verify: `PY -m pytest tests/unit/test_compose_static.py -q`.

- [ ] 5.5 Fechar a fase. Seção Fase 5 em `PHASE_REPORTS.md`.
  Verify: `PY -m pytest tests -q -m "not live_gemini"` verde.

**Fecha:** critério 10 (por AppTest e serviço real; chat com Gemini não verificado ao vivo). **Não verificado:** compose.

**Gate do revisor da fase 5** (`phase5-review.json`): roda AppTest e o health do Streamlit, confere que as 5 páginas existem e leem só a API, que nada depende da chave para as páginas 2 a 5.

---

## Fase 6: Validation (critérios 11, 12; relatório final)

### Itens

- [ ] 6.1 Segurança. `tests/security/`: nenhuma credencial hard-coded (varredura em teste lendo os arquivos do repositório rastreados por `git ls-files`), `.env` ignorado, logs de uma sessão de `/chat` falho e de `/tools` não contêm `GEMINI_API_KEY` nem senhas (captura com `caplog` e arquivo `logs/`), SQL injection via `/tools/query_metric` (filtros, dimensões, `order_by`), limites de payload, `poc_app`/`poc_reader` já cobertos na Fase 2.
  Verify: `PY -m pytest tests/security -q`.

- [ ] 6.2 Desempenho. `scripts/bench_query.py` mede p50/p95 de `query_metric` (8 métricas × 3 recortes, 30 repetições cada) via API real; registra em `PHASE_REPORTS.md`. Teste `tests/integration/test_perf_smoke.py` falha se p95 > 2 s (limite generoso para detectar regressão grosseira).
  Verify: `PY scripts/bench_query.py` imprime a tabela; `PY -m pytest tests/integration/test_perf_smoke.py -q`.

- [ ] 6.3 README pt-BR (`README.md`). Visão geral, diagrama curto, pré-requisitos, passos exatos sem Docker (`scripts/bootstrap.sh`, `pg_local start`, `make migrate load etl quality sync`, subir API e Streamlit), passos com Docker (marcados não verificados), configuração do Gemini (`GEMINI_API_KEY`, `GEMINI_MODEL=gemini-2.5-flash` não verificado, onde conferir o nome), papel do Cosmos e limitações (sync grava conhecimento `active`, API interna `transition_episode`, perguntas em texto claro, sem autenticação real, 1 worker uvicorn), execução de testes, roteiro de demonstração com as 7 perguntas exemplo e as 3 de borda, solução de problemas.
  Verify: ver 6.5.

- [ ] 6.4 Reconciliação e suíte final. `make test` roda `pytest -m "not live_gemini"`; `python -m pipelines.quality.run` e `compute_golden` executados do zero.
  Verify: `PY -m pytest -q -m "not live_gemini"` verde (anotar contagem de testes) e `PY -m pytest -m live_gemini -q` com `skipped`.

- [ ] 6.5 Teste do README (critério 12). Em clone limpo (`git clone` do repositório local para diretório temporário, sem `.venv`, `pgdata`, `.vendor`, `*.duckdb`), seguir **literalmente** os comandos do README sem Docker até API e Streamlit respondendo (`/health`, `/_stcore/health`, uma chamada `/tools/query_metric`). Corrigir o README onde o passo falhar. Se o clone limpo não for possível por rede (clone do Cosmos), registrar a limitação exata.
  Verify: saídas dos comandos coladas no relatório; todos os processos encerrados.

- [ ] 6.6 Relatório de aceite `docs/ACCEPTANCE_REPORT.md` (pt-BR): tabela dos 12 critérios com status `VERIFICADO POR EXECUÇÃO`, `PARCIAL` ou `NÃO VERIFICADO`, comando, saída resumida e caminho da evidência em `docs/evidence/`. Declarar honestamente: critérios 5 e 6 não verificados ao vivo (sem chave; o que foi provado até a fronteira), Docker/compose não executados, admissão oficial do Cosmos contornada, `gemini-2.5-flash` não validado, captura de tela se não houve navegador. Atualizar `PHASE_REPORTS.md` com a fase 6.
  Verify: cada linha "VERIFICADO" aponta para comando reexecutável; `PY -m pytest -q -m "not live_gemini"` verde na última linha do relatório.

**Fecha:** 11, 12; consolida 1 a 10.

**Gate do revisor da fase 6** (`phase6-review.json`): reexecuta a suíte e o roteiro do README, rejeita qualquer critério marcado verificado sem comando e saída, e rejeita qualquer teste roteirizado ou stub apresentado como verificação de Gemini ou Docker.

---

## Decisões e suposições deste plano

- **Sem reestruturação do workflow.** As fases são sequenciais e acopladas pelos mesmos bancos e pelo mesmo grafo Cosmos. Os loops existentes `p2-loop` a `p6-loop` (revisor escrevendo `.agents/tasks/phaseN-review.json` com `verdict`) permanecem como estão; este arquivo é a única fonte do plano.
- Versões do `requirements.txt` são as provisórias do ARCHITECTURE seção 12; se um pin não instalar, o coder escolhe a versão estável compatível mais próxima e registra.
- Reembolso `completed` é o único que conta em `net_revenue`/`refund_amount`; `order_count` conta todos os pedidos (ARCHITECTURE seção 6).
- O endpoint `GET /overview` e os de leitura (`/catalog`, `/quality`, `/etl`, `/audit`) foram adicionados à API porque o frontend só chama a API; o ARCHITECTURE não os lista, mas não os contradiz.
- `ops.generator_state` e a ordem 2.4/2.5 (qualidade antes do ETL) são detalhes de implementação não definidos no ARCHITECTURE.
- `.agents/` está no `.gitignore`: os artefatos de revisão não são commitados.
