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
