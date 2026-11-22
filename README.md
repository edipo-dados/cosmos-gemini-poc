# Cosmos Semantic + Gemini: POC de Analytics Conversacional

Plataforma de analytics em linguagem natural. O usuário pergunta em português, o Gemini escolhe ferramentas governadas, o Query Engine monta SQL controlado sobre o DuckDB e a resposta volta com número, SQL, regras de negócio e evidências. O Cosmos Semantic guarda o catálogo semântico, as capacidades e a trilha de decisões.

> **Estado da verificação.** Tudo o que não depende de Docker ou de chave do Gemini foi executado de verdade (ver `docs/ACCEPTANCE_REPORT.md`). **Chamadas ao Gemini real e o Docker Compose não foram verificados**, porque o ambiente de desenvolvimento não tinha chave nem Docker. O código dessas partes existe e é testado até a fronteira (SDK real com transporte roteirizado; análise estática do Compose).

## 1. Visão geral

| Camada | Tecnologia | Papel |
|---|---|---|
| OLTP | PostgreSQL 16 (`analytics_poc`) | 8 tabelas com PK, FK, índices e constraints; dados sintéticos Faker pt_BR, seed configurável |
| Analytics | DuckDB (arquivo `analytics.duckdb`) | 4 dimensões e 4 fatos, carregados por ETL a partir do PostgreSQL |
| Semântica | YAML em `semantic/` + Cosmos | YAML é a fonte da verdade; `semantic.sync_to_cosmos` grava no World do Cosmos |
| Query Engine | Python | Valida métrica, dimensões e filtros, monta SQL parametrizado, executa em DuckDB somente leitura |
| LLM | Google Gemini (`google-genai`) | Function calling com 7 ferramentas; não recebe SQL nem acesso ao banco |
| API | FastAPI | `/chat`, `/ask`, `/tools/{nome}`, catálogo, qualidade, auditoria, evidência |
| Interface | Streamlit | 5 páginas (Assistente, Catálogo, Qualidade, SQL e Evidências, Visão Geral) |

Volumes gerados (seed 42, 24 meses até 2026-10-31): 5.000 clientes, 500 produtos, 20 categorias, 5 regiões, 20.000 pedidos, 47.617 itens, 20.000 pagamentos e 7.194 reembolsos.

## 2. Arquitetura e relação Cosmos / Gemini / bancos

```
Usuário ─► Streamlit ──HTTP──► FastAPI ─┬─► Orquestrador Gemini (function calling)
                                        │        │ 7 ferramentas declaradas
                                        │        ▼
                                        └─► ToolExecutor ─► Cosmos (autorização + episódio + resultado)
                                                 │
                                                 ├─► SemanticReader (catálogo YAML sincronizado no Cosmos)
                                                 ├─► Query Engine ─► DuckDB (somente leitura)
                                                 └─► audit.query_audit (PostgreSQL)
PostgreSQL (OLTP) ─ETL─► DuckDB ─ reconciliação e regras de qualidade ─► ops.* (PostgreSQL)
```

- **O Cosmos não executa consultas analíticas.** Ele não é uma camada semântica SQL. Neste projeto ele guarda atores, métricas, dimensões, termos do glossário, regras e capacidades no World (`.cosmos/`), valida o grafo (`cosmos validate`) e registra, para cada chamada de ferramenta, a decisão de autorização, o episódio e o resultado no SQLite do runtime. A execução do SQL é do Query Engine, escrito neste repositório.
- **O Gemini não escreve SQL nem acessa banco.** Ele só chama as 7 ferramentas (`search_concepts`, `explain_metric`, `list_metrics`, `query_metric`, `list_dimensions`, `show_sql`, `get_evidence`). Não existe ferramenta de SQL livre; `POST /tools/execute_sql` devolve 404.
- **Bancos:** o PostgreSQL é a origem; o DuckDB é o único banco consultado pelas métricas. Papéis de PostgreSQL separados (admin, loader, reader, dq, app) com permissões mínimas.
- **Dados com inconsistências controladas** ficam isolados em `dq_lab.duckdb` e no esquema `dq_lab` do PostgreSQL. Nunca entram nas métricas oficiais.

Documentos de apoio: `docs/ARCHITECTURE.md` (decisões e tabela de capacidades do Cosmos comprovadas e não comprovadas), `docs/COSMOS_DISCOVERY.md`, `cosmos/documentation/USO_DO_COSMOS.md`, `docs/PHASE_REPORTS.md`, `docs/ACCEPTANCE_REPORT.md`.

## 3. Pré-requisitos

- macOS ou Linux, Python 3.11+ (o `.venv` do projeto usa 3.11.18), `git`.
- `uv` (`pip install --user uv`) para o `bootstrap.sh`.
- Acesso à internet na instalação (PyPI e GitHub, para o Cosmos).
- Opcional: chave do Google AI Studio para o chat; Docker para o Compose.

## 4. Configuração (variáveis de ambiente)

```bash
cp .env.example .env     # o .env é ignorado pelo git; troque todas as senhas "troque-me-*"
```

| Variável | Padrão | Uso |
|---|---|---|
| `GEMINI_API_KEY` | vazio | Chave do Google AI Studio. Sem ela, o chat responde 503 `gemini_not_configured` e o resto funciona |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Modelo Gemini. Este nome não foi validado contra a API real |
| `PG_HOST`, `PG_PORT`, `PG_DATABASE` | `127.0.0.1`, `54329`, `analytics_poc` | PostgreSQL |
| `PG_ADMIN_PASSWORD`, `PG_LOADER_PASSWORD`, `PG_READER_PASSWORD`, `PG_DQ_PASSWORD`, `PG_APP_PASSWORD` | placeholders | Senhas dos papéis |
| `DUCKDB_PATH`, `DQ_LAB_DUCKDB_PATH` | `analytics.duckdb`, `dq_lab.duckdb` | Arquivos DuckDB |
| `SEED`, `DATA_END_DATE` | `42`, `2026-10-31` | Geração determinística. Os valores esperados dos testes assumem estes padrões |
| `COSMOS_WORLD_DIR` | `.` | Diretório do World do Cosmos |
| `API_URL` | `http://localhost:8000` | Endereço da API usado pelo Streamlit |

Para o chat, exporte a chave no shell (nunca grave no código): `export GEMINI_API_KEY=...` e, se quiser, `export GEMINI_MODEL=...`. A chave não é registrada nos logs.

## 5. Execução local, sem Docker

PostgreSQL real e local via pacote `pgserver` (sem Docker).

```bash
bash scripts/bootstrap.sh     # venv, dependências, Cosmos no commit fixado e World (cosmos init)
make pg-start                 # PostgreSQL 16 em 127.0.0.1:54329, dados em pgdata/
make migrate                  # esquema, papéis, índices e constraints
make load                     # gera dados (SEED=42 por padrão) e carrega o PostgreSQL; reexecutar não duplica
make etl                      # PostgreSQL -> DuckDB (analytics.duckdb), com logs em logs/etl.log
make quality                  # regras de qualidade, reconciliação PG x DuckDB e laboratório de inconsistências
make sync                     # YAML semântico -> Cosmos + cosmos validate
make metric-tests             # testes de validação das 8 métricas contra SQL de referência
```

`make data` executa `pg-start migrate load etl quality` em sequência. Troque a seed com `SEED=7 make load` (os testes golden assumem a 42). Para parar o banco: `make pg-stop`.

### API

```bash
.venv/bin/uvicorn app.api.main:app --port 8000      # com GEMINI_API_KEY exportada para habilitar o chat
curl localhost:8000/health
curl -X POST localhost:8000/tools/query_metric -H 'content-type: application/json' \
  -d '{"metric":"net_revenue","dimensions":["region"],"order_by":{"field":"metric","direction":"desc"},"limit":1}'
```

Endpoints: `GET /health`, `POST /chat` e `/ask`, `POST /tools/{nome}`, `GET /catalog/metrics|dimensions|glossary`, `GET /evidence/{query_id}`, `GET /etl/runs`, `GET /quality/runs|results`, `GET /audit/queries`, `GET /overview`. Documentação interativa em `http://localhost:8000/docs`.

### Interface

```bash
API_URL=http://localhost:8000 .venv/bin/streamlit run app/frontend/Home.py --server.port 8501
```

Abra `http://localhost:8501`. As páginas 2 a 5 funcionam sem chave. O Assistente mostra um aviso sem chave e oferece a aba "Consulta direta de métrica".

### Testes

```bash
make test                                   # 266 testes, sem Gemini ao vivo
.venv/bin/python -m pytest tests/frontend   # páginas Streamlit com AppTest
GEMINI_API_KEY=... .venv/bin/python -m pytest -m live_gemini -q   # 14 testes com o Gemini real (exige chave válida e cota)
```

A suíte sobe um PostgreSQL temporário próprio; não depende do banco do `make pg-start`.

## 6. Execução com Docker (não verificada)

```bash
cp .env.example .env
docker compose up -d postgres
docker compose run --rm init          # cria o World do Cosmos, migra, carrega, roda ETL, qualidade e sync
docker compose up -d api frontend
```

Serviços: `postgres:16.2`, `init` (perfil `init`), `api` (porta 8000) e `frontend` (porta 8501), com health checks e volumes `pg_data`, `duckdb_data` e `cosmos_world`. **Estes arquivos nunca foram executados**: Docker não existe no ambiente onde a POC foi construída. Só a análise estática dos arquivos (`tests/unit/test_compose_static.py`) passou. Espere ajustes na primeira execução.

## 7. Perguntas de exemplo (roteiro de demonstração)

1. "Qual foi o faturamento dos últimos 30 dias?" (ambígua: o assistente usa a receita líquida e explica a escolha)
2. "Qual região teve a maior receita?"
3. "Qual categoria possui o maior ticket médio?"
4. "Quantos clientes ativos temos?"
5. "Compare o faturamento dos últimos dois meses."
6. "Qual é a taxa de cancelamento?"
7. "Explique como o faturamento líquido é calculado."
8. "Qual foi o lucro do último mês?" (métrica inexistente: o assistente deve recusar e listar as disponíveis)
9. "Quantos clientes ativos por categoria?" (dimensão não permitida: só região e segmento)

Roteiro: pergunte, abra "SQL executado" e "Evidências" na resposta, confira o mesmo `query_id` na página SQL & Evidência, veja a regra na página Catálogo Semântico, rode `make quality` e veja a página Qualidade de Dados detectar as inconsistências do laboratório sem afetar a Visão Geral. As 19 perguntas com resultado esperado pré-calculado por SQL independente no PostgreSQL estão em `tests/golden/questions.json` e `tests/golden/expected.json` (recalcular: `make golden`).

## 8. Estrutura

```
app/{api,frontend,services}  agent/{gemini,tools,orchestration}  cosmos/documentation
data/generators  database/{migrations,postgres}  pipelines/{extract,transform,quality}
semantic/{metrics,dimensions,rules,glossary}  scripts  tests/{unit,integration,security,frontend,golden,live}
docs/  Dockerfile  docker-compose.yml  Makefile  requirements.txt  .env.example
```

## 9. Segurança

Segredos só por ambiente; `.env` fora do git. Consultas analíticas em DuckDB somente leitura, com limite de linhas e timeout. Argumentos validados no backend; SQL sempre parametrizado e montado pelo Query Engine. Papéis de PostgreSQL com permissão mínima. Logs sem chave de API. Auditoria em `audit.query_audit` (pergunta, usuário, métrica, filtros, SQL, data/hora, fonte, resultado, evidências, decisão do Cosmos).

## 10. Limitações conhecidas

- **Gemini ao vivo não verificado.** Não se sabe se o modelo escolhe as ferramentas certas, responde em português ou se `gemini-2.5-flash` é aceito. Os testes de chat usam o SDK real com transporte roteirizado, que não é o Gemini.
- **Docker e Compose não verificados** (sem Docker no ambiente).
- A interface Streamlit foi testada por AppTest e por serviço real (HTTP 200), mas não foi vista em navegador.
- O Cosmos está em Developer Preview e fixado no commit `464175f`. O projeto usa só os recursos comprovados em `docs/ARCHITECTURE.md`.
- O `.venv` e as versões foram validados em macOS arm64. `pgserver` é só para desenvolvimento local.
- Sem autenticação de usuários: o usuário vem do cabeçalho `X-User-Id` (padrão `demo`), sem verificação de identidade. Adequado só a uma POC.
- O 504 `query_timeout` na API não tem teste próprio (o timeout está testado no Query Engine).
