# Arquitetura de integração: Cosmos + Gemini + PostgreSQL + DuckDB

Este documento fixa as decisões da Fase 1. Ele depende de `docs/history/COSMOS_DISCOVERY.md` (fatos sobre o Cosmos, com rótulos PROVEN, DOCUMENTED-ONLY e UNPROVEN) e de `docs/history/ENV_CHECK.md` (ambiente). A pilha tecnológica da seção 12 fica travada em famílias após a aprovação; números de versão são provisórios (ver seção 12).

## 1. Visão geral

O usuário faz uma pergunta no Streamlit. O Streamlit chama a API FastAPI. A API abre um episódio no runtime do Cosmos para a pergunta e envia a pergunta ao Gemini (SDK `google-genai`) com as 7 declarações de ferramentas. O Gemini nunca recebe acesso a banco. Quando pede uma ferramenta, a API passa a chamada pelo `AuthorizationGateway` e pelo `ToolAdapter` do Cosmos, que concede ou nega a ação `tool.invoke` e grava a decisão em SQLite. O handler da ferramenta consulta o **grafo semântico** (arquivo `.cosmos/graph.json`, escrito a partir de `semantic/*.yaml`) ou o **Query Engine**. O Query Engine valida a solicitação contra o catálogo, monta SQL parametrizado e executa em DuckDB aberto como somente leitura. Cada chamada grava uma linha em `audit.query_audit` no PostgreSQL. O Gemini redige a resposta em português com base nos resultados. A interface mostra resposta, números, gráfico, métricas, dimensões, filtros, SQL e evidências.

```text
Streamlit ──HTTP──> FastAPI ──> Orquestrador Gemini (google-genai, loop manual de function calling)
                                   │ chamada de ferramenta
                                   ▼
                      ToolExecutor (único ponto de entrada, audita em finally)
                        ├─ Cosmos AuthorizationGateway + ToolAdapter  ──> .cosmos/runtime.sqlite3 (decisões, eventos)
                        └─ handlers das 7 ferramentas
                              ├─ SemanticReader ──> .cosmos/graph.json (conhecimento semântico no Cosmos)
                              └─ QueryEngine ─────> analytics.duckdb (read_only=True)
                                                   audit.* ──> PostgreSQL (poc_app, INSERT/SELECT; UPDATE só em chat_turn)

semantic/*.yaml ──sync──> .cosmos/graph.json        (YAML é a fonte de verdade; teste confere o conteúdo)
PostgreSQL oltp ──ETL──> analytics.duckdb           (só schema oltp; dq_lab nunca entra)
```

## 2. Papel do Cosmos e componentes adicionais

O Cosmos **não é** uma camada semântica SQL (ver `history/COSMOS_DISCOVERY.md`, seções 2 e 6, itens 23 e 24). Ele não tem catálogo de métricas, não gera SQL e não tem conector de banco documentado ou presente no código lido. O único ponto de extensão para operações externas é um registro genérico de handlers (`ToolAdapter` e `ExternalSystemAdapter`, `runtime/cosmos_runtime/effects.py:302` e `:334`), sem driver de banco. No POC ele faz três coisas comprovadas:

1. **Guarda o conhecimento semântico** (métricas, dimensões, regras de negócio, glossário com sinônimos, versão e responsável) como nós e arestas validados pelo esquema do Cosmos em `.cosmos/graph.json`. O servidor MCP somente leitura do Cosmos e o nosso `SemanticReader` leem esse mesmo arquivo.
2. **Governa as ferramentas do agente**: cada chamada de ferramenta é um `AttemptedEffect` com ação `tool.invoke` e `resource_ref` `tool:<nome>`. Sem capacidade concedida, o gateway nega por padrão. A capacidade existe como nó `capability` no grafo (formato da seção 5.2) e o projeto a converte para o formato de estado que o gateway consome (seção 5.3).
3. **Registra proveniência de execução**: tarefa, episódio, decisão de autorização, resultado e evidência ficam em `.cosmos/runtime.sqlite3`. A tabela de auditoria do PostgreSQL guarda o `cosmos_episode_id` e o `cosmos_decision_id` para ligar as duas trilhas.

Componentes que o Cosmos não oferece e que o projeto implementa:

| Componente | Responsabilidade | Local |
|---|---|---|
| Geradores e carga | Dados sintéticos (Faker pt_BR), PostgreSQL | `data/generators`, `pipelines/extract` |
| ETL | PostgreSQL → DuckDB, dimensões e fatos | `pipelines/transform` |
| Qualidade e reconciliação | Verificações de integridade e comparação entre bancos | `pipelines/quality` |
| Catálogo semântico (fonte de verdade) | YAML de métricas, dimensões, regras, glossário | `semantic/` |
| Sync Cosmos | YAML → nós do grafo, validação e leitura de volta | `semantic/sync_to_cosmos.py` |
| Query Engine | Validação, construção de SQL controlado, execução em DuckDB | `app/services/query_engine` |
| Adaptador de ferramentas | 7 ferramentas, gateway Cosmos, auditoria | `agent/tools` |
| Cliente e orquestração Gemini | Function calling, limites de iteração | `agent/gemini`, `agent/orchestration` |
| API e interface | FastAPI e Streamlit | `app/api`, `app/frontend` |

## 3. Capacidades comprovadas e não comprovadas

Citações são caminhos dentro de `.vendor/cosmos/`. Detalhes e saídas em `history/COSMOS_DISCOVERY.md`, seção 5.

| Capacidade do Cosmos | Rótulo | Citação | Uso no projeto |
|---|---|---|---|
| Instalar o pacote no Python 3.11 | PROVEN | `pyproject.toml`; Discovery 5.2 | Instalar a partir do commit fixado |
| `cosmos init`, `validate`, `status` | PROVEN | `tools/cosmos.py`; Discovery 5.3, 5.4 | Criar e validar o World do projeto |
| `cosmos doctor` | PROVEN que falha aqui (sem `pnpm`) | Discovery 5.4 | Não usar |
| Hooks git gerados | PROVEN que apontam para caminho Windows | Discovery 5.3 | Não ativar |
| Esquema de registros e `validate_graph` | PROVEN | `schemas/cosmos-record.schema.json`; `tools/validate_ontology.py` | Validar o grafo antes de gravar |
| Persistir `entity` (`poc.metric`), `knowledge` (`rule`) e aresta `core.governed_by` no `graph.json` | PROVEN (script próprio, validador do Cosmos) | `spec/ontology/*.md`; Discovery 5.6; `docs/evidence/phase1/proto_sync.out` | Catálogo semântico no Cosmos |
| Nó `capability` `tool.invoke` com `grantee_refs` e `resources` ExternalLocator `{system, uri}` | PROVEN (validado por `validate_graph` e usado no gateway) | `spec/ontology/CAPABILITY.md`; `IDENTITY-AND-REFERENCES.md`; Discovery 5.9; `docs/evidence/phase1/spike_capability_graph.out` | Política de ferramentas |
| Fluxo oficial de admissão de conhecimento (Candidate Intake) | DOCUMENTED-ONLY | `runtime/README.md`; `docs/CAPABILITIES.md` | Contornado pelo sync; declarado no README |
| MCP stdio somente leitura (`cosmos_query`, `cosmos_tool`, `cosmos_explain`, `cosmos_path`) | PROVEN execução das quatro, em World descartável (`cosmos_explain` e `cosmos_path` em `docs/evidence/phase1/mcp_explain.out`); suporte oficial UNPROVEN. Não provado sobre o grafo do sync real (Fase 3) | `tools/cosmos_mcp_server.py`; Discovery 5.7 | Leitura do grafo; teste de contrato |
| Busca por sinônimo no MCP | UNPROVEN (o código não filtra `aliases`) | `tool_query` | Feita no `SemanticReader` |
| Context binding nativo para perguntas analíticas | UNPROVEN | Discovery 5.8 | Não depender. O contexto vem de `search_concepts` e `explain_metric` |
| `ToolAdapter` + `AuthorizationGateway` (permitir e negar) | PROVEN | `runtime/cosmos_runtime/effects.py`, `authorization.py`; Discovery 5.9 | Governança das 7 ferramentas |
| O gateway carregar sozinho os nós `capability` do `graph.json` | UNPROVEN. O código do gateway só aceita o `dict` do `authority_state_provider` | `authorization.py:_state` | O projeto escreve o provider (seção 5.3) e o prova com o spike da Fase 1 e o teste de contrato |
| Eventos duráveis no SQLite do runtime | PROVEN | Discovery 5.8, 5.9 | Proveniência de execução |
| `OpenAICompatibleActorAdapter` | DOCUMENTED-ONLY | `runtime/cosmos_runtime/actors.py` | Não usar |
| Gemini via Cosmos | UNPROVEN | Discovery 6, item 19 | Gemini é chamado direto pelo `google-genai` |
| Studio, Observatory, Control Center | DOCUMENTED-ONLY | `docs/QUICKSTART.md` | Fora do escopo |
| Execução de SQL ou consulta analítica | Sem conector de banco documentado ou presente no código lido. `ExternalSystemAdapter` (`effects.py:334`) é um registro de handlers por `(action, resource_ref)` com `AuthorizedEffect`, sem driver | `effects.py:302-360`; Discovery 6, item 23 | Query Engine próprio (seção 6); ver 5.3 sobre a escolha do adaptador |
| Serviço Cosmos em contêiner | Sem `Dockerfile` ou compose no repositório do Cosmos (busca vazia) | Discovery 6, item 24 | Biblioteca dentro da imagem da API |

## 4. As 7 ferramentas do agente

Regra do POC: ferramenta é nativa do Cosmos só quando o Cosmos faz a operação. Nenhuma das 7 tem equivalente nativo completo. Todas passam pelo gateway do Cosmos (seção 5.3).

| Ferramenta | Equivalente nativo | Decisão | Implementação |
|---|---|---|---|
| `search_concepts(query)` | `cosmos_query` filtra por substring em `display_name`, `summary`, `statement`, `description`. Não filtra `aliases` | **Adaptador** | `SemanticReader` normaliza texto (minúsculas, sem acento) e compara com `display_name`, `aliases` e `description` dos nós `poc.metric`, `poc.dimension`, `poc.glossary_term`. Devolve até 10 resultados com `type`, `name`, `business_name`, `matched_alias` |
| `explain_metric(metric)` | `cosmos_explain` devolve nó, arestas e vizinhos de um ID | **Nativo + adaptador de formatação** | O adaptador converte o nome técnico em ID (`stable_cosmos_ref`), chama `tools.cosmos_mcp_server.tool_explain` e formata fórmula, denominador, filtros, tratamento de status, dimensões permitidas, responsável, versão e regras ligadas por `core.governed_by` |
| `list_metrics()` | `cosmos_tool` lista só nós `capability`. `cosmos_query` ignora filtro por `entity_type` | **Adaptador** | `SemanticReader` filtra nós com `entity_type == "poc.metric"` |
| `list_dimensions(metric?)` | Nenhum | **Adaptador** | Mesmo princípio; com `metric`, devolve só as dimensões permitidas dessa métrica |
| `query_metric(metric, dimensions, filters, date_from, date_to, order_by, limit)` | Nenhum (Cosmos não executa consultas) | **Adaptador + Query Engine** | Seção 6 |
| `show_sql(query_id)` | Nenhum | **Adaptador** | Lê `sql_text` e `sql_params` de `audit.query_audit` pelo `query_id` devolvido por `query_metric` |
| `get_evidence(query_id)` | Eventos de runtime no SQLite do Cosmos guardam decisão e o retorno do handler (só `str` é truncada em 2048; um `dict` é gravado inteiro) | **Adaptador** | Junta a linha de auditoria (resultado completo até 1000 linhas), versão do catálogo, `etl_run_id`, contagem de linhas e referências Cosmos (`cosmos_episode_id`, `cosmos_decision_id`) |

Exposição ao Gemini: apenas as 7 declarações. As ferramentas `cosmos_open` e `cosmos_act` do MCP não são expostas.

## 5. Decisões de integração

### 5.1 Gemini

Cliente `google-genai`, chamada direta, **loop manual de function calling** com a chamada automática desativada. Motivo: cada chamada precisa passar pelo gateway do Cosmos e ser auditada, o que a chamada automática do SDK esconderia. Alternativa descartada: usar o `OpenAICompatibleActorAdapter` do Cosmos contra um endpoint compatível do Gemini. Motivo: DOCUMENTED-ONLY, sem prova de compatibilidade, e a tarefa exige o SDK oficial.

- `GEMINI_API_KEY` (obrigatória para chat) e `GEMINI_MODEL` (obrigatória para chat). O `.env.example` traz `GEMINI_MODEL=gemini-2.5-flash`, valor verificado contra a API real em 2026-11-22 (ver ACCEPTANCE_REPORT); o README manda conferir o nome na documentação do Google AI Studio. Nome inválido: o SDK devolve 404 na primeira chamada e a API responde HTTP 503 `gemini_model_invalid` (fatal até corrigir o `.env`, log ERROR).
- Máximo de 6 iterações de ferramenta por pergunta; temperatura 0; instrução de sistema em português que proíbe inventar números e exige citar o `query_id`.
- Sem chave: a API sobe normalmente. `GET /health` informa `gemini: "not_configured"`. `POST /chat` retorna HTTP 503 com `{"error":{"code":"gemini_not_configured"}}`. As ferramentas e o Query Engine continuam acessíveis por `POST /tools/{name}` para testes e para a página SQL & Evidence. A integração fica implementada e testada até a fronteira (construção das declarações com os tipos do SDK, loop de orquestração com modelo roteirizado, mapeamento de erros). Esses testes **não verificam o Gemini** e o relatório não pode apresentá-los como verificação. Os critérios 5 e 6 só ficam "verificados por execução" com chave real.
- Erros do Gemini: 429 e 5xx, até 2 novas tentativas com espera exponencial (1 s, 2 s), depois HTTP 502 `llm_unavailable` (recuperável pelo cliente, log WARNING). 401 e 403: HTTP 503 `gemini_auth_failed` (fatal até corrigir a chave, log ERROR sem a chave). Resposta bloqueada por segurança: HTTP 200 com `status:"blocked"` e mensagem fixa em português. Limite de iterações: HTTP 200 com `status:"incomplete"`.

### 5.2 Fonte de verdade do catálogo e relação com o Cosmos

`semantic/` (YAML versionado em git) é a **fonte de verdade**. O Cosmos recebe uma projeção.

- `semantic/sync_to_cosmos.py`: lê o YAML, valida o YAML com `jsonschema` (esquemas em `semantic/schema/`), monta os registros, valida com `tools.validate_ontology.validate_graph` e grava `.cosmos/graph.json` de forma atômica (arquivo temporário e `os.replace`), preservando os nós criados por `cosmos init`. IDs vêm de `stable_cosmos_ref("metric:<nome>")` e equivalentes, então reexecutar não duplica.
- **Propriedade e remoção.** Todo registro (nó ou aresta) gerado pelo sync leva `extensions["poc.sync"] = {"owner": "semantic-sync", "catalog_version": "<hash do catálogo>"}`. A cada execução o sync remove do grafo todo registro com `owner == "semantic-sync"` e toda aresta ligada a ele, e regrava o conjunto gerado a partir do YAML. Registros sem esse marcador (os do `cosmos init`) ficam intactos. Assim, uma métrica, regra, sinônimo ou ferramenta removida do YAML some do grafo e o gateway passa a negá-la.
- **World ausente.** O sync nunca cria o World nem o grafo. Se `cosmos.environment.json` ou `.cosmos/graph.json` não existir, sai com código 2 e a mensagem `world_not_initialized` (fatal, log ERROR). Quem cria o World é `scripts/bootstrap.sh` (seção 13).
- Mapeamento: métrica → `entity` com `entity_type: "poc.metric"` e `extensions["poc.metric"]` (nome de negócio, fórmula, fonte, dimensões, filtros, responsável, versão, testes); dimensão → `poc.dimension`; termo de glossário → `poc.glossary_term` com `aliases` em português; regra de negócio → `knowledge` com `knowledge_class: "rule"`, `lifecycle_state: "active"`, `scope_refs` apontando para a métrica; aresta `core.governed_by` entre a métrica e cada regra; nó `capability` por ferramenta, no formato validado pelo spike da Fase 1: `action: "tool.invoke"`, `decision: "allow"`, `grantee_refs: [<id do actor poc.agent>]`, `resources: [{"system": "poc-tools", "uri": "tool:<nome>"}]` (ExternalLocator, `spec/ontology/IDENTITY-AND-REFERENCES.md`, seção "External locators"; uma string solta não é `ResourceRef` válido, `CAPABILITY.md`). O sync também grava dois nós `actor`: `poc.agent` (`actor_type: service`, é o `execution_actor_ref` e o `grantee_refs`) e `poc.user` (`actor_type: human`, é o `requester_ref`). Mapeamento explícito: `resources[0].uri` do nó é igual ao `resource_ref` passado a `new_attempt` e ao `tool_ref` registrado em `ToolAdapter.register`; o nó do grafo e o `resource_ref` do runtime são dois formatos ligados por essa igualdade, testada.
- Teste `tests/integration/test_cosmos_sync.py` (verifica o conteúdo no Cosmos): depois do sync, lê `.cosmos/graph.json` pelo servidor MCP do Cosmos em subprocesso (com `env={"COSMOS_GRAPH": <caminho absoluto>}` e `cwd=<World temporário>`, porque `resolve_graph_path` cairia em outro grafo e `load_graph` devolve `[]` em silêncio; o teste afirma `count > 0` de nós `poc.metric` antes de comparar conteúdo) e confere que as 8 métricas, as 9 dimensões, as regras e todos os sinônimos do YAML estão presentes com a mesma versão e os mesmos textos. Como `cosmos_query` não filtra `aliases`, o teste obtém cada nó por `cosmos_query {"where": {"id": stable_cosmos_ref(...)}}` ou `cosmos_explain {"id": ...}` e compara `aliases`, `description` e `extensions` do registro devolvido com o YAML. Também confere que `cosmos_explain` de cada métrica lista suas regras por `core.governed_by` (prova o que o protótipo 5.6 só validou em formato). Um segundo teste altera o YAML em diretório temporário, roda o sync e confirma que o grafo muda (detecta sync que não propaga). O mesmo arquivo exige `validate_graph(...) == []` e `cosmos validate` com `valid: true`.
- O Query Engine lê **o YAML**, não o grafo, para montar SQL. O Cosmos serve ao agente como explicação e política. Um teste garante que cada métrica do YAML tem a mesma versão no grafo (impede divergência silenciosa entre explicação e execução).
- Alternativa descartada: Query Engine ler as fórmulas do grafo do Cosmos. Motivo: o Cosmos não valida expressões SQL e o grafo é uma projeção; um erro de sync mudaria números.
- O conjunto de ferramentas permitidas existe em um único arquivo, `semantic/rules/agent_capabilities.yaml`, que gera os nós `capability`. Um teste confere que os `uri` dos nós são exatamente os 7 nomes registrados no `ToolAdapter`. Outro remove uma ferramenta de `agent_capabilities.yaml`, roda o sync, confirma que o nó sumiu do grafo (sem órfãos com `owner == "semantic-sync"`) e que o gateway nega a ferramenta.
- Limitação declarada no README: o sync grava conhecimento já `active` e não passa pelo fluxo de admissão do Cosmos (Discovery 5.6).

### 5.3 Governança de ferramentas no Cosmos

**Escolha do adaptador.** As 7 ferramentas usam `ToolAdapter`, não `ExternalSystemAdapter`. `ToolAdapter` (`effects.py:302`) exige a ação `tool.invoke`, recusa ferramenta não registrada e rejeita `nested_effects`, o que casa com "o Gemini só chama ferramentas declaradas". `ExternalSystemAdapter` (`effects.py:334`) aceita qualquer par `(action, resource_ref)`; seria o candidato para um recurso "DuckDB", mas isso faria o Cosmos parecer o executor da consulta e exigiria uma ação própria (`metric.query`) por recurso. Decisão: o Cosmos autoriza a **ferramenta**; o Query Engine executa a consulta dentro do handler. O `ExternalSystemAdapter` não é usado.

**Pré-requisitos no início da API (lifespan do FastAPI).** Falha em qualquer item impede a API de subir (fatal, log ERROR):

1. O World existe em `COSMOS_WORLD_DIR` (padrão `.`): `cosmos.environment.json` e `.cosmos/graph.json`, criados por `scripts/bootstrap.sh` (seção 13) e preenchidos pelo sync. A API não cria o World; se faltar, não sobe (`world_not_initialized`). `environment_ref` vem de `cosmos.environment.json` (campo `environment_id`).
2. O `graph.json` contém os nós `actor` `poc.agent` e `poc.user` e um nó `capability` `tool.invoke` por ferramenta (gravados pelo sync, seção 5.2). Os ids são lidos por `stable_cosmos_ref("actor:poc.agent")` e `stable_cosmos_ref("actor:poc.user")`. O grafo também precisa ter ao menos um nó `entity` com `entity_type == "poc.metric"` (`SemanticReader`, seção 5.5); sem isso a API não sobe (`semantic_catalog_unavailable`).
3. `build_services(RuntimeConfig(database_path=<world>/.cosmos/runtime.sqlite3, environment_ref=<acima>))`; `ToolAdapter(services)` com as 7 ferramentas registradas como `tool:<nome>`; `AuthorizationGateway(services, provider)`.
4. O `provider(episode_id)` lê `.cosmos/graph.json` (com cache por `mtime`), pega os nós `capability` com `decision == "allow"` e devolve `{"capabilities": [{"capability_id": <id do nó>, "grantee_refs": <do nó>, "action": <do nó>, "decision": "allow", "resources": [x["uri"] for x in resources if x["system"] == "poc-tools"], "constraints": {}, "task_ref": <task do episódio>}], "approvals": [], "delegations": []}`. `task_ref` vem de `services.store.get_episode(episode_id).task_ref`. Esse mapeamento foi executado em `scripts/spikes/spike_capability_graph.py` (PROVEN para o formato e o gateway); o que continua sem prova é uma carga nativa do Cosmos, que não existe (seção 3). Se o provider não conseguir ler o grafo, devolve `{"capabilities": [], ...}`, o que **nega tudo** (fail closed).

**Sequência por pergunta** (`/chat`) ou por chamada direta (`/tools/{name}`). Cada chamada a `/tools/{name}` abre um episódio novo com `objective="tool:<nome>"` e `idempotency_key=f"tool:{uuid4()}"`. Sem chave única, `intake` (`runtime/cosmos_runtime/intake.py`, `_key_for`) calcula a chave por hash de objetivo, solicitante, ambiente e escopo e devolve o episódio antigo, já `COMPLETED`, com `created=False`; a transição `CREATED→PREPARING` falharia na segunda chamada. Se `intake_objective` devolver `created=False`, a API trata como erro interno (`cosmos_runtime_unavailable`) e não tenta transição. Regra de concorrência: o `threading.Lock` global protege **apenas** operações no `SQLiteRuntimeStore` (`intake_objective`, `transition_episode`, `new_attempt`, `authorize_effect`, `ToolAdapter.execute`). O Query Engine nunca roda dentro do lock. Todos os endpoints do FastAPI são `def` síncronos (threadpool do FastAPI), nunca `async def`, para que o lock não bloqueie o event loop e `/health` responda durante uma consulta lenta.

1. `services.intake_objective(ObjectiveRequest(objective=<pergunta>, requester_ref=<id poc.user>, execution_actor_ref=<id poc.agent>, environment_ref=<env>, idempotency_key=<turn_id>))` devolve `task` e `episode_id`.
2. `services.store.transition_episode(episode_id, PREPARING, expected_state=CREATED)` e depois `(READY, expected_state=PREPARING)`. **Isto é API interna**: `transition_episode` não consta em `runtime/README.md`; o padrão vem de `runtime/tests/test_sandbox_adapters.py:47`. O produto é "Developer Preview". Mitigação: o commit fica fixado e `tests/integration/test_cosmos_contract.py` executa essa sequência completa; se a API mudar, o teste falha.
3. Para cada chamada de ferramenta do Gemini (um episódio, N tentativas), o `ToolExecutor` segue esta ordem (prova em `scripts/spikes/spike_toolexecutor_handoff.py`, saída em `docs/evidence/phase1/spike_toolexecutor_handoff.out`):
   1. **Esquema, antes do gateway.** Validação Pydantic (`extra="forbid"`, tamanhos da seção 6.1). Falha: `invalid_arguments`, linha `rejected` em `audit.query_audit` com `cosmos_decision_id` nulo, **sem** `new_attempt` e sem `runtime.adapter.result`. Assim o Gemini ou o cliente HTTP nunca controla o conteúdo que o Cosmos grava em `parameters`.
   2. **Autorização (lock curto).** O executor gera `query_id = uuid4()` e chama `gateway.new_attempt(episode_id=..., action="tool.invoke", resource_ref="tool:<nome>", parameters={"query_id": "<uuid>", "arguments": <argumentos validados>})` e `gateway.authorize_effect(effect)`, que devolve `AuthorizedEffect` (`decision.decision_id` vai para `audit.query_audit.cosmos_decision_id`). Se negar (`AuthorizationBlocked`), nada executa e `execute` não é chamado.
   3. **Domínio e execução (fora do lock), só depois do `allow`.** Catálogo, matriz, valores categóricos, Query Engine ou `SemanticReader`. O executor grava o resumo em `ToolExecutor.pending[query_id] = {"row_count", "status"}` (dict em memória, protegido por seu próprio `threading.Lock` curto, separado do lock do store). Falha de domínio (`unknown_metric`, `dimension_not_allowed`, ...) ou `query_timeout` gravam `{"row_count": 0, "status": "rejected" | "error"}`.
   4. **Registro (segundo lock curto).** `ToolAdapter.execute(authorized)` é chamado para **toda** chamada autorizada, inclusive as que terminam em `rejected` ou `error`. O handler (registrado uma vez por ferramenta) não executa consulta: faz `pending.pop(params["query_id"])` e devolve `{"query_id", "row_count", "status"}`. Chave ausente: levanta `AdapterBoundaryError` (linha "exceção do handler" da tabela de falhas). Se o executor falhar antes de `execute` (exceção entre 2 e 4), remove a entrada de `pending` em bloco `finally`, para não vazar memória.
   
   Regra resultante: cada decisão `allow` tem exatamente um `runtime.adapter.result`; cada `deny` e cada `invalid_arguments` têm zero. O handler nunca reexecuta a consulta. Teste em `test_cosmos_contract.py`: chamada com `unknown_metric` gera exatamente um `runtime.authorization.decision` e um `runtime.adapter.result`; chamada com campo extra gera nenhum dos dois e grava `rejected` com `cosmos_decision_id` nulo; chamada negada gera uma decisão e nenhum `adapter.result`; `pending` fica vazio ao final.
4. No fim da pergunta: `READY → RUNNING → COMPLETED` para `ok`, `incomplete` e `blocked`; `READY → FAILED` para `error`. Cada transição usa `expected_state`. O ciclo `CREATED → … → COMPLETED` foi executado no spike; `READY → FAILED` está na tabela de transições (`model.py`) e é coberto pelo teste de contrato. Episódios que ficam abertos por queda do processo permanecem em `READY` no SQLite e não são retomados; isso é inofensivo e declarado.
5. `session_id` não gera episódio: cada pergunta é um episódio independente. O Gemini recebe o histórico da sessão da memória da API (`session_id`, até 20 turnos, descartado no reinício).

**Falhas** (log e retorno):

| Falha | Recuperável | Retorno | Auditoria e log |
|---|---|---|---|
| `AuthorizationBlocked` (capacidade ausente) | Sim | Ao Gemini: `{"error":{"code":"tool_not_authorized"}}` | `query_audit.status=rejected`; WARNING |
| `AdapterBoundaryError` (ferramenta não registrada) ou exceção do handler | Não para a chamada | Ao Gemini: `internal_error`; HTTP 500 em `/tools` | `status=error`; ERROR com traceback |
| Qualquer outra exceção de `intake_objective`, `transition_episode`, `new_attempt`, `authorize_effect` ou do SQLite (`database is locked`, disco cheio) | Não | **Fail closed**: a ferramenta **não** executa; `/chat` e `/tools` respondem HTTP 503 `cosmos_runtime_unavailable` | `status=error`, `error_code=cosmos_runtime_unavailable`; ERROR |
| `SemanticReader` sem grafo legível ou sem nós `poc.metric` (`semantic_catalog_unavailable`) | Não até corrigir o World | HTTP 503; ao Gemini, o mesmo código | `status=error`; ERROR |
| Falha ao gravar o resultado em `ToolAdapter._record` depois de o handler rodar | Não | Mesmo 503; o resultado não é usado | `status=error`; ERROR |

- SQLite do runtime: `store.py:37` liga `PRAGMA journal_mode = WAL`, que permite leitores concorrentes e **um escritor por vez**. A API roda com **um processo uvicorn** e o `threading.Lock` evita `database is locked` entre threads. Isso limita a concorrência do POC e é declarado.
- Limite do Cosmos: `_safe_value` (`effects.py:58`) trunca só `str` acima de 2048; um `dict` do handler seria gravado inteiro em `.cosmos/runtime.sqlite3`. Por isso o handler registrado no `ToolAdapter` devolve somente `{"query_id", "row_count", "status"}`. O resultado completo vai ao Gemini pelo `ToolExecutor` e à tabela de auditoria no PostgreSQL.
- Privacidade: o texto da pergunta é gravado em **texto claro** em dois lugares, `.cosmos/runtime.sqlite3` (`ObjectiveRequest.objective`; fora do git) e `audit.chat_turn.question`. O POC não filtra dados pessoais digitados pelo usuário. O README declara isso.

### 5.4 Banco de consultas

DuckDB é o único banco que o Query Engine consulta. O PostgreSQL serve ao OLTP, à auditoria, ao registro de execuções e à reconciliação.

### 5.5 `SemanticReader` e falhas das ferramentas semânticas

O `SemanticReader` lê `<COSMOS_WORLD_DIR>/.cosmos/graph.json` por **caminho explícito** e não usa `load_graph` do Cosmos (que engole qualquer erro e devolve `[]`, e busca o arquivo por `$COSMOS_GRAPH` e `cwd`). Cache por `mtime`. Se o arquivo faltar, não parsear, não for lista ou não tiver nenhum nó `poc.metric`, levanta `semantic_catalog_unavailable` (HTTP 503, log ERROR, auditoria `error`). Vale para `search_concepts`, `list_metrics`, `list_dimensions` e `explain_metric`. Para `explain_metric`, o adaptador chama `tool_explain` (servidor MCP do Cosmos, importado como função) e trata `"error" in resultado` como `internal_error` (HTTP 500): a métrica já passou pelo catálogo YAML, então ID ausente no grafo indica divergência entre YAML e grafo. Sem esse teste, o dict de erro seria formatado como se fosse uma métrica. Comportamento provado em `spike_toolexecutor_handoff.out` (quatro casos de grafo inválido, erro de `tool_explain` e subprocesso com `COSMOS_GRAPH` e `cwd` fixos). Pendente de prova: o mesmo comportamento sobre o grafo do sync real (Fase 3).

## 6. Query Engine

Entrada de `query_metric`, validada no backend (`app/services/query_engine/validation.py`, modelos Pydantic):

| Campo | Obrigatório | Tipo e regras | Falha |
|---|---|---|---|
| `metric` | sim | string `^[a-z][a-z0-9_]{0,63}$`, deve existir no catálogo | `unknown_metric` com a lista de métricas e sugestões por similaridade |
| `dimensions` | não | lista de até 3 nomes únicos, todos marcados `S` na matriz abaixo para a métrica. No máximo uma entre `date`, `month`, `year`. `monthly_revenue_growth` exige `month` | `dimension_not_allowed` com a lista permitida; `invalid_dimension_combination`; `missing_required_dimension` |
| `filters` | não | até 5 itens `{dimension, op, value}`; `op` em `eq`, `in`, `gte`, `lte`, `between`; dimensão marcada `S` na matriz para a métrica (filtros e dimensões usam a mesma matriz; filtro por `date`, `month` ou `year` é rejeitado para `active_customers`); tipo do valor conforme a dimensão (data ISO `YYYY-MM-DD`, mês `YYYY-MM`, ano inteiro 2000 a 2100, textos até 64 caracteres, `in` até 50 valores). Valores categóricos são conferidos contra os valores existentes no DuckDB, em cache indexado por `etl_run_id` (ver abaixo) | `invalid_filter` |
| `date_from`, `date_to` | não | data ISO; `date_from <= date_to`; ambas dentro do intervalo dos dados. Quando ausentes, a métrica usa todo o intervalo. Para `active_customers`: `date_to` é o `as_of` e `date_from` é rejeitado | `invalid_date_range` |
| `order_by` | não | `metric` ou uma das dimensões pedidas; `direction` `asc` ou `desc` | `invalid_order` |
| `limit` | não | inteiro de 1 a 1000, padrão 100 | `invalid_limit` |

Construção do SQL (`sql_builder.py`):

- Os identificadores (tabelas, colunas, expressões de métrica, junções) vêm só do catálogo YAML. Nenhum texto do usuário ou do Gemini entra no SQL. Valores de filtro entram como parâmetros `?` do DuckDB.
- Cada métrica declara no YAML `source`, `expression`, `base_filter` (regras de status) e `joins` por dimensão. O builder compõe `SELECT <dimensões>, <expressão> AS value FROM ... WHERE <base_filter> AND <filtros> GROUP BY ... ORDER BY ... LIMIT ?`.
- Antes de executar, uma checagem defensiva exige uma única instrução que comece por `SELECT` ou `WITH` e proíbe `;` fora de literais. A garantia real de somente leitura é a conexão `duckdb.connect(path, read_only=True)`.
- Timeout de 10 s por consulta: um temporizador chama `connection.interrupt()`; erro `query_timeout`. Limite de linhas: o `limit` validado, mais corte duro de 1000.
- Cada requisição abre uma conexão de curta duração. Isso permite que o ETL troque o arquivo por renomeação atômica (seção 9). Na mesma conexão o Query Engine lê `etl_meta` (seção 9) e obtém o `etl_run_id` do arquivo realmente aberto. O cache de valores categóricos (regiões, segmentos, categorias, produtos, formas de pagamento, status) é indexado por `etl_run_id` e recarregado quando o valor muda, então um novo ETL não exige reiniciar a API.

Regras de negócio fixadas aqui para que a Fase 3 não decida arquitetura. A tabela completa (denominadores, status, janelas) vai para `semantic/rules/*.yaml`.

| Decisão | Regra |
|---|---|
| Status de pedido | `pending`, `paid`, `cancelled`, `refunded` (todos os itens reembolsados integralmente). Reembolso parcial mantém `paid` |
| Pedido pago | `status IN ('paid','refunded')` (houve captura de pagamento) |
| Pagamento | 1 por pedido, 20.000 no total. `payments.status`: `captured` (pagos e reembolsados), `pending`, `voided` (cancelados) |
| Reembolso | 1 por item reembolsado (`refunds.order_item_id`), valor menor ou igual ao total do item. Efetivado: `refunds.status = 'completed'`. Outros status (`pending`, `rejected`) não contam |
| Base de tempo | Todas as métricas usam a data do pedido (`fact_orders.order_date`). Reembolsos são atribuídos à data do pedido de origem |
| `gross_revenue` | Soma de `order_items.line_total` dos pedidos pagos (antes de reembolsos) |
| `net_revenue` | `gross_revenue` menos soma dos reembolsos efetivados dos mesmos pedidos |
| `order_count` | Todos os pedidos, de qualquer status (mesmo universo do denominador de `cancellation_rate`) |
| `average_order_value` | `net_revenue` dividido por pedidos pagos distintos; `NULL` se o denominador for 0 |
| `active_customers` | Clientes distintos com ao menos um pedido pago com `order_date` em `[as_of - 89 dias, as_of]` (90 dias corridos, incluindo `as_of`). `as_of` é o `date_to` da chamada; sem `date_to`, é `DATA_END_DATE`, nunca a data do sistema. `date_from` é rejeitado com `invalid_date_range`. Aceita só as dimensões região e segmento |
| `cancellation_rate` | Pedidos `cancelled` dividido por todos os pedidos, no mesmo recorte; razão de 0 a 1 |
| `refund_amount` | Soma dos reembolsos efetivados |
| `monthly_revenue_growth` | `net_revenue` do mês dividido pelo do mês anterior menos 1. A série mensal é montada sobre um calendário de todos os meses do histórico (meses sem venda valem 0), filtrada pelas dimensões e filtros categóricos e **antes** do filtro de data; o `LAG` particiona pelas demais dimensões (região, segmento). `date_from` e `date_to` só restringem os meses **retornados**, de modo que o primeiro mês da janela usa o mês anterior real. `NULL` no primeiro mês do histórico e quando o mês anterior é 0. `order_by` e `limit` são aplicados depois do cálculo. Dimensão `month` obrigatória; região e segmento permitidas |
| Categoria e produto | Permitidas para `gross_revenue`, `net_revenue`, `refund_amount`, `average_order_value` e `order_count` (pedidos distintos com item da categoria). Reembolsos são por item, então a atribuição é exata. Não permitidas para `active_customers`, `cancellation_rate` e `monthly_revenue_growth` |
| Forma de pagamento e status | Conforme a matriz abaixo. Forma de pagamento vem de `payments.method` (todo pedido tem 1 pagamento, inclusive cancelados). Status vem de `orders.status`; para métricas de pedidos pagos, o recorte por status só devolve `paid` e `refunded` |
| Valores monetários | `NUMERIC(12,2)` no PostgreSQL, `DECIMAL(12,2)` no DuckDB, `Decimal` em Python; JSON como string decimal e `value_display` formatado em reais |

Matriz métrica × dimensão (`S` permitida como dimensão e como filtro, `N` rejeitada com `dimension_not_allowed`). Fica copiada em `semantic/metrics/*.yaml` (campo `allowed_dimensions`) e um teste confere que o YAML é igual a esta tabela.

| Métrica | date | month | year | region | segment | category | product | payment_method | order_status |
|---|---|---|---|---|---|---|---|---|---|
| `gross_revenue` | S | S | S | S | S | S | S | S | S |
| `net_revenue` | S | S | S | S | S | S | S | S | S |
| `order_count` | S | S | S | S | S | S | S | S | S |
| `average_order_value` | S | S | S | S | S | S | S | S | S |
| `active_customers` | N | N | N | S | S | N | N | N | N |
| `cancellation_rate` | S | S | S | S | S | N | N | S | N |
| `refund_amount` | S | S | S | S | S | S | S | S | S |
| `monthly_revenue_growth` | N | S (obrigatória) | N | S | S | N | N | N | N |

Justificativas: `cancellation_rate` por `order_status` é 0 ou 1 e por categoria ou produto mistura pedidos com vários itens, então é `N`. `monthly_revenue_growth` só existe por mês, e `date` e `year` quebram a série. `active_customers` usa janela fixa, então dimensões de tempo, categoria, produto, pagamento e status são `N`. Para `order_count` por categoria ou produto, conta pedidos distintos com item daquele recorte. A pergunta de um usuário por uma combinação `N` gera `dimension_not_allowed` e o teste de dimensão não autorizada usa `active_customers` com `category`.

`DATA_END_DATE` (padrão `2026-10-31`) e `SEED` (padrão `42`) vêm do ambiente. O histórico cobre 24 meses terminando em `DATA_END_DATE`. A ferramenta `list_metrics` devolve `data_range` e `data_as_of` para o Gemini resolver "últimos 30 dias".

Resultado de `query_metric`: `{query_id, metric, business_name, rows[], columns[], row_count, truncated, filters_applied, source, catalog_version, etl_run_id, duration_ms}`. O SQL não vai no corpo da resposta ao Gemini; `show_sql` o devolve sob demanda.

### 6.1 Validação das demais entradas

Erros HTTP usam `{"error":{"code":"...","message":"..."}}`. Para chamadas do Gemini, o mesmo objeto volta como resposta da função. Camada dona: modelos Pydantic em `app/api/schemas.py` (`extra="forbid"`), porque a API é a fronteira de confiança; o Gemini e o cliente HTTP são tratados como entrada não confiável.

| Entrada | Obrigatória | Regra | Falha |
|---|---|---|---|
| `POST /chat` corpo | sim | JSON de até 16 KiB | HTTP 413 `payload_too_large`; JSON inválido ou campo extra: 400 `invalid_request` |
| `question` | sim | string, após `strip` de 1 a 2000 caracteres | 400 `invalid_question` |
| `session_id` | não | `^[A-Za-z0-9_.-]{1,64}$`; padrão: UUID novo | 400 `invalid_session_id` |
| Cabeçalho `X-User-Id` | não | `^[A-Za-z0-9_.-]{1,64}$`; ausente vale `demo` | 400 `invalid_user_id` (valor presente e inválido não é trocado por `demo`, porque o valor vai para log e auditoria) |
| `POST /tools/{name}` | `name` sim | um dos 7 nomes | 404 `unknown_tool` (não grava `query_audit`, pois não há ferramenta; log WARNING) |
| Corpo de `/tools/{name}` | sim | objeto JSON validado pelo modelo da ferramenta, `extra="forbid"`. Acontece **antes** do gateway (seção 5.3, passo 1) | 400 `invalid_arguments`, auditado como `rejected` com `cosmos_decision_id` nulo |
| `search_concepts.query` | sim | string, após `strip` de 1 a 200 caracteres | `invalid_arguments` (400, esquema) |
| `explain_metric.metric`, `list_dimensions.metric` | `explain_metric` sim; `list_dimensions` não | padrão `^[a-z][a-z0-9_]{0,63}$` (esquema) e existência no catálogo (domínio) | formato inválido: `invalid_arguments` (400, esquema); formato válido e ausente do catálogo: `unknown_metric` (422, domínio, depois do `allow`) |
| `show_sql.query_id`, `get_evidence.query_id` | sim | UUID (formato textual; esquema) | `invalid_arguments` (400, esquema) |
| Posse do `query_id` | n/a | só devolve linhas de `audit.query_audit` com o mesmo `user_id` da requisição; outro `user_id` equivale a inexistente | `query_not_found` (HTTP 404) |
| `show_sql` sobre chamada rejeitada ou sem SQL | n/a | `sql_text` nulo | `no_sql_available` (HTTP 409). `get_evidence` devolve `status`, `error_code` e as regras da validação, sem linhas |

Corpo de erro sempre `{"error":{"code","message","query_id"?}}`. Status HTTP por código de ferramenta (em `POST /tools/{name}`; no `/chat` o mesmo objeto volta ao Gemini como resposta da função e o HTTP segue 200):

| Código | HTTP |
|---|---|
| `invalid_arguments` (falha de esquema Pydantic) | 400 |
| `unknown_metric`, `dimension_not_allowed`, `invalid_dimension_combination`, `missing_required_dimension`, `invalid_filter`, `invalid_date_range`, `invalid_order`, `invalid_limit` (validação de domínio) | 422 |
| `tool_not_authorized` | 403 |
| `query_not_found` | 404 |
| `no_sql_available` | 409 |
| `query_timeout` | 504 |
| `audit_failed`, `internal_error` | 500 |
| `cosmos_runtime_unavailable`, `semantic_catalog_unavailable` | 503 |

**Regra de classificação (esquema x domínio).** Falha de **esquema** é qualquer violação verificável só com o argumento recebido, sem consultar catálogo, banco ou auditoria: tipo, campo extra (`extra="forbid"`), tamanho de `query`, formato UUID de `query_id`, regex de `metric`. Sempre vira `invalid_arguments` (400), antes do gateway, sem `new_attempt`, com `cosmos_decision_id` nulo. Os detalhes (campo e regra violada) vão em `message`, nunca em outro código. Os códigos `invalid_query` e `invalid_query_id` **não existem**. Falha de **domínio** exige consultar catálogo, matriz, DuckDB ou auditoria e acontece depois do `allow`, com um `runtime.adapter.result`: `unknown_metric` (formato válido, ausente do catálogo), `dimension_not_allowed`, `invalid_dimension_combination`, `missing_required_dimension`, `invalid_filter`, `invalid_date_range`, `invalid_order`, `invalid_limit`, `query_not_found`, `no_sql_available`. Os campos de `query_metric` das linhas `dimensions`, `filters`, `date_*`, `order_by` e `limit` da seção 6 têm o tipo checado no esquema (`invalid_arguments`) e o conteúdo checado no domínio (códigos da própria tabela).

Todas as falhas desta tabela são recuperáveis pelo chamador e não derrubam a API. Falhas de ferramenta (`invalid_arguments`, `query_not_found`, `no_sql_available`, `unknown_metric`, e os demais códigos de domínio) geram linha em `audit.query_audit` com `status=rejected`. Falhas do corpo de `/chat` (`question`, `session_id`, `X-User-Id`, tamanho) não criam turno e não geram linha; só log INFO. `unknown_tool` gera log WARNING.

Testes de contrato desta regra (`test_cosmos_contract.py`): `show_sql` com `query_id="abc"` gera 400 `invalid_arguments`, nenhuma decisão e nenhum `adapter.result` no SQLite, e linha `rejected` com `cosmos_decision_id` nulo; `search_concepts` com `query=""` idem; `explain_metric` com `metric="X-1"` idem; `explain_metric` com `metric="metrica_x"` gera 422 `unknown_metric`, uma decisão e um `adapter.result`; `show_sql` com UUID válido inexistente gera 404 `query_not_found`, uma decisão e um `adapter.result`. Provado para três ferramentas (stub) em `spike_toolexecutor_handoff.out`, bloco "Rodada 4, achado 1".

## 7. Ambiguidade, métrica inexistente e dimensão não autorizada

- Pergunta ambígua (por exemplo "receita" sem dizer bruta ou líquida): a instrução de sistema manda o Gemini perguntar ao usuário ou explicar a escolha, consultando `explain_metric`. `search_concepts` devolve as duas métricas candidatas para "receita". Não há regra de negócio escondida no código.
- Métrica inexistente: `unknown_metric` (recuperável). O Gemini recebe a lista válida e responde que não existe.
- Dimensão não autorizada: `dimension_not_allowed` (recuperável), auditoria `rejected`.
- Os três casos têm testes de API sem Gemini (chamando `POST /tools/query_metric`) e testes do loop com modelo roteirizado.

## 8. Permissões de bancos e usuários

PostgreSQL, banco `analytics_poc`, schemas `oltp`, `dq_lab`, `audit`, `ops`:

| Papel | Uso | Permissões |
|---|---|---|
| `poc_admin` | migrações (DDL) | dono do banco e dos schemas. Usado só por `database/migrations` |
| `poc_loader` | geradores e carga | `USAGE` nos schemas `oltp` e `dq_lab`; `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `SELECT` nas tabelas desses schemas; `INSERT`, `SELECT`, `UPDATE` em `ops`. Sem DDL, sem acesso a `audit` |
| `poc_reader` | extração do ETL e reconciliação | `SELECT` em `oltp` e `ops`; **sem nenhum acesso a `dq_lab`**. Conexão com `default_transaction_read_only = on` |
| `poc_dq` | testes de qualidade | `SELECT` em `oltp` e `dq_lab`; `INSERT` em `ops.dq_*` |
| `poc_app` | API (auditoria e leitura de status) | `INSERT`, `SELECT` em `audit.*`; `UPDATE` somente nas colunas `answer`, `status`, `gemini_model`, `cosmos_episode_id` de `audit.chat_turn`; `SELECT` em `ops`. Sem `DELETE` e sem `UPDATE` em `audit.query_audit`; sem acesso a `oltp` |

O ETL usa **duas conexões**: `poc_reader` para extrair de `oltp` e `poc_loader` apenas para gravar `ops.etl_run`. A reconciliação lê `oltp` com `poc_reader` e grava `ops.dq_*` com `poc_dq`. Nenhuma conexão de leitura escreve.

Senhas só por variáveis de ambiente (`PG_ADMIN_PASSWORD`, `PG_LOADER_PASSWORD`, `PG_READER_PASSWORD`, `PG_DQ_PASSWORD`, `PG_APP_PASSWORD`). `.env` fica no `.gitignore`; `.env.example` traz placeholders. Logs usam um filtro que redige `GEMINI_API_KEY` e senhas. Teste de segurança: abre conexão como `poc_reader` e confirma que `INSERT` em `oltp.customers` e `SELECT` em `dq_lab.*` falham; abre como `poc_app` e confirma que `UPDATE audit.query_audit`, `DELETE` em `audit.*` e `UPDATE audit.chat_turn SET question=...` falham, e que a transição `ok` → `error` em `chat_turn` também falha.

DuckDB: `analytics.duckdb` é escrito apenas pelo ETL. A API e o Query Engine abrem com `read_only=True`. Um segundo arquivo, `dq_lab.duckdb`, existe só para a demonstração de divergência e nunca é aberto pela API.

## 9. Tabela de auditoria

Schema `audit`, criada por migração. `audit.query_audit` é só inserção (sem `UPDATE` nem `DELETE`, por permissão e gatilho). `audit.chat_turn` é inserida no **início** da pergunta com `status='started'` e recebe **um** `UPDATE` controlado no fim: `GRANT UPDATE (answer, status, gemini_model, cosmos_episode_id) ON audit.chat_turn TO poc_app` e um gatilho `BEFORE UPDATE` que só aceita a transição de `status='started'` para um status final e rejeita qualquer mudança em `question`, `user_id`, `session_id`, `created_at`, `request_id`. `DELETE` é rejeitado. Isso mantém a FK `query_audit.turn_id → chat_turn` válida, pois as linhas de `query_audit` são gravadas durante a pergunta. Se o processo cair, o turno fica `started`, o que é um sinal legítimo de interrupção.

`audit.chat_turn`: `turn_id uuid pk`, `created_at timestamptz not null`, `user_id text not null`, `session_id text not null`, `question text not null` (até 2000 caracteres, texto claro; o mesmo texto vai ao SQLite do Cosmos, seção 5.3, e o POC não filtra dados pessoais digitados), `answer text`, `status text not null` (`started`, `ok`, `incomplete`, `blocked`, `error`), `gemini_model text`, `cosmos_episode_id text`, `request_id text not null`.

`audit.query_audit` (uma linha por chamada de ferramenta, inclusive as rejeitadas):

| Coluna | Tipo | Observação |
|---|---|---|
| `query_id` | uuid pk | devolvido ao Gemini |
| `turn_id` | uuid fk → `chat_turn` | nulo quando chamado por `/tools` direto |
| `created_at` | timestamptz not null | UTC |
| `user_id` | text not null | cabeçalho `X-User-Id` validado (seção 6.1); padrão `demo` (sem autenticação real, declarado). `show_sql` e `get_evidence` só leem linhas do mesmo `user_id` |
| `tool_name` | text not null | uma das 7 |
| `metric` | text | |
| `dimensions` | jsonb | |
| `filters` | jsonb | filtros e período |
| `row_limit` | int | |
| `sql_text` | text | SQL com `?` |
| `sql_params` | jsonb | valores dos parâmetros |
| `source` | text | por exemplo `duckdb:analytics.duckdb` |
| `etl_run_id` | bigint | lido da tabela `etl_meta` dentro do `analytics.duckdb` aberto naquela requisição (execução do ETL que gerou o arquivo lido) |
| `catalog_version` | text | hash do catálogo YAML |
| `status` | text not null | `ok`, `rejected`, `error` |
| `error_code` | text | |
| `row_count` | int | |
| `duration_ms` | int | |
| `result` | jsonb | até 1000 linhas |
| `evidence` | jsonb | regras aplicadas, denominador, filtros base, contagens |
| `cosmos_episode_id`, `cosmos_decision_id` | text | ligação com o SQLite do Cosmos. `cosmos_decision_id` aceita `NULL`: é nulo para `invalid_arguments` e `unknown_tool` (a chamada nunca chegou ao gateway) e para erros de `cosmos_runtime_unavailable` antes da decisão. Para `tool_not_authorized` guarda o id da decisão `deny`, se o gateway a gravar; senão `NULL` |

`etl_meta(etl_run_id BIGINT, finished_at TIMESTAMP, source_row_counts JSON)`: o ETL a grava dentro do `analytics.duckdb` temporário, com o mesmo `etl_run_id` de `ops.etl_run`, **antes** da troca atômica do arquivo. Assim o `etl_run_id` descreve o arquivo, não uma tabela externa. Teste: rodar o ETL duas vezes com dados diferentes e conferir que `etl_run_id` e a lista de valores categóricos aceitos mudam sem reiniciar a API.

Dono da invariante "toda chamada de ferramenta é auditada": o `ToolExecutor` (único caminho de execução), com a gravação em bloco `finally`. Se a gravação de auditoria falhar, a chamada retorna `audit_failed` ao Gemini e ao usuário, log ERROR, e o resultado não é usado. Motivo: resposta sem rastro viola o requisito.

## 10. Isolamento dos dados de qualidade

Invariante: dados com inconsistências nunca alimentam métricas oficiais.

- **Dados oficiais**: schema `oltp` (com PKs, FKs, CHECKs e UNIQUEs) e `analytics.duckdb`, construído só a partir de `oltp`. O gerador produz um conjunto válido para `oltp`.
- **Laboratório de defeitos**: schema `dq_lab`, com as mesmas tabelas **sem FKs nem CHECKs**, para que as linhas inválidas possam existir. O gerador injeta defeitos controlados e determinísticos (seed fixa) e grava um manifesto `tests/golden/dq_expected.json` com a contagem esperada por regra. Defeitos: pedidos sem cliente, itens sem produto, pagamentos duplicados, cancelados com pagamento capturado, reembolso acima do valor pago, valores negativos, datas inconsistentes (reembolso antes do pedido, pedido no futuro), e uma divergência de métrica entre `dq_lab` e `dq_lab.duckdb`.
- **Quem lê o quê** (cada garantia tem um dono):
  - O ETL extrai com `poc_reader`, que não tem permissão em `dq_lab`. Dono: permissões do PostgreSQL.
  - O ETL tem uma lista fixa de tabelas de origem (`oltp.*`). Dono: código do ETL, coberto por teste que inspeciona a consulta.
  - O Query Engine só abre `analytics.duckdb`. Dono: configuração `DUCKDB_PATH`, e um teste confirma que uma contagem por métrica não muda após carregar o `dq_lab`.
- **Duas execuções de verificações**: as mesmas regras (`pipelines/quality/rules/*.sql`) rodam (a) em `oltp`, onde o resultado esperado é 0 violações, e uma falha **bloqueia a carga no DuckDB** (o ETL aborta antes de trocar o arquivo); e (b) em `dq_lab`, onde o resultado esperado é o do manifesto, o que prova que cada regra detecta o defeito.
- Reconciliação PostgreSQL × DuckDB: para cada uma das 8 métricas, uma SQL de referência escrita à mão contra `oltp` (`pipelines/quality/reference_sql/*.sql`, independente do Query Engine) é comparada com o resultado do Query Engine. Dinheiro e contagens têm tolerância 0. Razões têm tolerância 1e-9.
- Resultados vão para `ops.dq_run` e `ops.dq_result`, que a página Data Quality lê.

## 11. Plano do Docker Compose

`docs/history/ENV_CHECK.md` informa que `docker` e `docker compose` **não estão disponíveis** e o daemon está indisponível. Decisão: escrever `docker-compose.yml` e os `Dockerfile`s, **sem poder verificá-los por execução**. O caminho verificado é a execução local com PostgreSQL 16.2 real do `pgserver` (`scripts/pg_local.py start|stop`, porta 54329, dados em `pgdata/`). O relatório final declara isso.

Serviços:

| Serviço | Imagem | Detalhes |
|---|---|---|
| `postgres` | `postgres:16.2` | volume `pg_data`; variáveis do `.env`; `healthcheck: pg_isready -U poc_admin -d analytics_poc`; scripts de papéis em `database/postgres/init/` |
| `init` | imagem do app | executa uma vez (`depends_on: postgres healthy`): migrações, geração, carga, ETL, qualidade, sync Cosmos. Perfil `init`; comando `docker compose run --rm init` |
| `api` | imagem do app | uvicorn com 1 worker; volumes `duckdb_data` e `cosmos_world` (montado em `/world`); `COSMOS_WORLD_DIR=/world`; `healthcheck: GET /health` |
| `frontend` | imagem do app | `streamlit run app/frontend/Home.py`; `API_URL=http://api:8000`; `healthcheck: /_stcore/health` |

Não há serviço Cosmos: o Cosmos é uma biblioteca Python instalada na imagem do app (Discovery, seção 2).

**World no contêiner (verificado por execução com Docker Compose em 2026-11-22).** O `cosmos init` exige um repositório git **com ao menos um commit** (provado: sem `.git`, falha com "requires an existing Git repository"; com `git init` sem commit, falha em `git rev-parse HEAD`; Discovery 5.3). A imagem não carrega `.git` e `cosmos.environment.json` e `.cosmos/` são as duas metades do World. Decisão: o World inteiro mora em um volume `cosmos_world` montado em `/world`. O serviço `init` executa `scripts/cosmos_world_init.sh`: se `/world/cosmos.environment.json` não existir, roda `git init`, grava um `README.md` mínimo, faz um commit com identidade passada por `-c user.name/-c user.email`, executa `cosmos init /world` e remove `/world/.githooks`; depois roda o sync com `COSMOS_WORLD_DIR=/world`. Reexecutar é seguro (o `cosmos init` pula o bootstrap quando manifesto e grafo existem, Discovery 5.3). O `cosmos.environment.json` do clone local é ignorado pelo git (seção 13), portanto não entra na imagem. A sequência `git init` + commit + `cosmos init` + `validate` foi executada com sucesso em diretório temporário local (`scripts/spikes/spike_capability_graph.py`); o encaixe em volume Docker foi confirmado depois pelo `docker compose run --rm init`. Comandos: `cp .env.example .env`, `docker compose up -d postgres`, `docker compose run --rm init`, `docker compose up -d api frontend`.

A imagem do app instala o Cosmos clonando o commit fixado em `/opt/cosmos` e executando `pip install -e /opt/cosmos` (o mesmo caminho do experimento 5.2).

## 12. Pilha tecnológica (famílias travadas na aprovação; versões provisórias)

Travadas em famílias principais: Python 3.11, PostgreSQL 16, FastAPI, DuckDB, google-genai, Streamlit, SQLAlchemy 2. Os números de versão da lista abaixo são provisórios até o congelamento da Fase 2 (`uv pip compile`); só `pydantic==2.14.4` foi instalado e verificado no `.venv` (spike de handoff). Python 3.11 (`.venv` já criado com CPython 3.11.18 via `uv`), Google Gemini via `google-genai`, Cosmos (commit `464175f6bfa641c30f0b2cdeb0ef84269fd202cb`, `cosmos-platform 1.6.0.dev1`), PostgreSQL 16, DuckDB, FastAPI com uvicorn, Streamlit com Plotly, SQLAlchemy 2 com psycopg 3, pandas, Faker (`pt_BR`), pytest, Docker Compose (escrito, não verificado).

Plano de dependências. As versões abaixo resultam de `uv pip compile --python-version 3.11` feito nesta fase. Nenhuma foi instalada ainda, com exceção das que já estão no `.venv` (`pgserver 0.1.4`, `jsonschema 4.26.0`, Cosmos). A Fase 2 instala, roda a suíte e congela com `uv pip compile`; se alguma versão falhar a instalação, a Fase 2 registra a troca em `docs/history/PHASE_REPORTS.md`.

```text
google-genai==3.6.1
duckdb==2.0.1
fastapi==0.165.0
uvicorn[standard]==0.54.0
streamlit==1.67.0
plotly==7.1.0
SQLAlchemy==2.1.9
psycopg[binary]==3.3.9
pandas==3.1.1
numpy==2.4.6
Faker==40.63.0
pydantic==2.14.4
pydantic-settings==2.16.3
PyYAML==6.0.4
httpx==0.28.1
jsonschema==4.26.0
pytest==9.2.0
pgserver==0.1.4          # só desenvolvimento local sem Docker
```

Cosmos não vai no `requirements.txt` por versão do PyPI (a publicação do `cosmos-platform` não foi verificada). `scripts/bootstrap.sh` clona o repositório no commit fixado em `.vendor/cosmos` e instala em modo editável. Fase 4 lê a API instalada do `google-genai` antes de escrever o cliente, porque o formato das chamadas de função depende da versão.

## 13. Estrutura final do repositório

A estrutura da tarefa foi ajustada em dois pontos: o World do Cosmos fica na **raiz** (o `cosmos init` resolve a raiz do git; Discovery 5.3), e `cosmos/worlds` não é criado.

```text
cosmos.environment.json            # criado por `cosmos init` em scripts/bootstrap.sh (ignorado pelo git; execução local, COSMOS_WORLD_DIR=.)
.cosmos/graph.json                 # criado por `cosmos init`, preenchido pelo sync (ignorado pelo git)
.cosmos/runtime.sqlite3            # estado do runtime (ignorado pelo git)
cosmos/documentation/              # notas do uso do Cosmos neste projeto
app/{api,frontend,services/query_engine}/
agent/{gemini,tools,orchestration}/
data/{generators,seeds,samples}/
database/{postgres/init,migrations,duckdb}/
pipelines/{extract,transform,quality/{rules,reference_sql}}/
semantic/{metrics,dimensions,rules,glossary,schema}/  + sync_to_cosmos.py
scripts/{bootstrap.sh,pg_local.py,compute_golden.py,cosmos_world_init.sh}
scripts/spikes/{spike_capability_graph.py,spike_tool_gateway.py,spike_toolexecutor_handoff.py,proto_sync.py}   # evidência repetível da Fase 1
docs/evidence/phase1/              # saídas dos spikes e de `cosmos validate`
tests/{unit,integration,golden,security}/
docs/ARCHITECTURE.md   docs/history/{TASK,ENV_CHECK,COSMOS_DISCOVERY,PHASE_REPORTS,IMPLEMENTATION_PLAN,ACCEPTANCE_REPORT}.md
docker-compose.yml  Dockerfile  requirements.txt  .env.example  README.md  Makefile
```

Não criar pacotes de topo chamados `tools` ou `runtime` no projeto: os nomes são ocupados pelo `cosmos-platform` instalado (`pyproject.toml` do Cosmos instala `runtime*` e `tools*`; `agent/tools` é seguro). Teste: `tests/unit/test_no_toplevel_name_clash.py` falha se existir `tools/` ou `runtime/` na raiz.

No contêiner o World fica em `/world` (seção 11). `cosmos.environment.json`, `.cosmos/` e `.githooks/` entram no `.gitignore` do projeto na Fase 3: o manifesto e o grafo são as duas metades do World, e como o `cosmos init` só pula o bootstrap quando **ambos** existem (`tools/cosmos.py:72`), versionar só o manifesto faria o `init` rebootstrapar e regravá-lo em clone novo. Regra única para clone novo: `scripts/bootstrap.sh` roda `cosmos init .` quando o manifesto não existe e depois remove `.githooks/` (não ativados; Discovery 5.3); em seguida `make sync` roda `semantic/sync_to_cosmos.py`, que nunca cria o World (seção 5.2). No contêiner vale `scripts/cosmos_world_init.sh` (seção 11).

## 14. Plano de entrega em fases e validação

Cada fase termina com os comandos abaixo executados e as saídas coladas em `docs/history/PHASE_REPORTS.md`. Fase não está concluída porque arquivos existem.

**Fase 1: Discovery (esta).** Validação: `docs/history/COSMOS_DISCOVERY.md` e este arquivo existem; `.vendor/cosmos` está no commit `464175f`; `.venv/bin/cosmos validate` roda em repositório descartável e retorna `valid: true`; `.venv/bin/python scripts/spikes/spike_capability_graph.py` imprime `validate_graph errors: []`, `ALLOWED` para `tool:list_metrics`, `DENIED` para `tool:query_metric` e `final episode state: completed` (saída já gravada em `docs/evidence/phase1/spike_capability_graph.out`); `scripts/spikes/spike_tool_gateway.py` e `proto_sync.py` reproduzem os experimentos 5.9 e 5.6 (saídas em `docs/evidence/phase1/`); `.venv/bin/python scripts/spikes/spike_toolexecutor_handoff.py` termina com `OK` e reproduz `docs/evidence/phase1/spike_toolexecutor_handoff.out` (handoff por `query_id`, ordem esquema → autorização → domínio, `SemanticReader`, classificação esquema x domínio).

**Fase 2: Data Foundation.**
1. `scripts/bootstrap.sh` e `uv pip install -r requirements.txt`.
2. `.venv/bin/python scripts/pg_local.py start` e `psql`-equivalente em Python mostrando `select version()`.
3. Migrações: papéis, schemas, tabelas com PKs, FKs, índices e CHECKs.
4. Geradores: `python -m data.generators.run --seed 42` com contagens 5.000, 500, 20, 5, 20.000, ≥35.000, 20.000, reembolsos > 0. Segunda execução: 0 linhas novas. Execução com outro seed sem `--reset`: código de saída 2.
5. ETL (extrai com `poc_reader`, grava `ops.etl_run` com `poc_loader`): `python -m pipelines.transform.run` cria `analytics.duckdb` com as 8 tabelas ou views, log em `logs/etl.log` e linha em `ops.etl_run`.
6. Qualidade e reconciliação: `python -m pipelines.quality.run` com 0 violações em `oltp`, contagens do manifesto em `dq_lab`, e 8 de 8 métricas reconciliadas.
7. Testes: `pytest tests/unit tests/integration -k "data or etl or quality"`. Teste de segurança de permissões. Teste do isolamento (seção 10).

**Fase 3: Semantic Governance.**
1. Transformar o spike da Fase 1 em `tests/integration/test_cosmos_contract.py`: provider lendo os nós `capability` do grafo real, sequência completa da seção 5.3 (intake, `READY`, tentativas, `COMPLETED` e `FAILED`), negação por nó removido.
2. `cosmos init` na raiz do projeto, remoção de `.githooks/`.
3. YAML das 8 métricas, 9 dimensões, regras e glossário; `python semantic/sync_to_cosmos.py`; `.venv/bin/cosmos validate .` com `valid: true`.
4. Query Engine e SQL de referência. `pytest tests/unit/test_query_engine.py tests/integration/test_cosmos_sync.py tests/integration/test_cosmos_contract.py tests/security`. Casos: SQL injection em filtros, dimensão não autorizada, métrica inexistente, limite, timeout (consulta artificialmente longa, por exemplo `range(1e10)`, para provar `connection.interrupt()` em conexão `read_only` do DuckDB; se falhar, registrar em `history/PHASE_REPORTS.md` e trocar o mecanismo), `active_customers` com `date_to` e com `date_from`, `monthly_revenue_growth` com janela de datas, `order_by` e `limit`, e a matriz da seção 6 contra o YAML.
5. Os testes de contrato do Cosmos executam o servidor MCP em subprocesso e a sequência de autorização. `test_cosmos_contract.py` inclui: chamar a mesma ferramenta duas vezes com os mesmos argumentos e esperar duas decisões `allow` em dois episódios distintos; `intake_objective` com `created=False` tratado como erro; `/health` respondendo durante uma consulta lenta; `POST /tools/{name}` com cada código de erro da seção 6.1 devolvendo o status esperado; transição de `chat_turn` `started` → final; o handoff por `query_id` e a ordem esquema → autorização → domínio (seção 5.3, passo 3); `semantic_catalog_unavailable` com grafo ausente, ilegível e sem `poc.metric`; `explain_metric` com ID ausente no grafo devolvendo `internal_error`. Nota: `cosmos-platform` foi instalado e testado em Python 3.11 (15 testes do próprio Cosmos), embora a documentação do Cosmos cite 3.12.

**Fase 4: Gemini Integration.**
1. Ler a API instalada de `google-genai`.
2. Cliente, 7 declarações, loop manual, `ToolExecutor`, auditoria, endpoint `POST /chat` e `POST /tools/{name}`.
3. Teste de fronteira: sem `GEMINI_API_KEY`, `/chat` retorna 503 `gemini_not_configured`.
4. 15 ou mais perguntas com resultados esperados calculados por SQL independente no PostgreSQL (`scripts/compute_golden.py` grava `tests/golden/expected.json`); o teste chama `query_metric` com os argumentos esperados e compara com o valor. Esse teste valida os **números do Query Engine**, não a escolha de ferramenta do Gemini.
5. Com `GEMINI_API_KEY` presente: `pytest -m live_gemini` roda as mesmas perguntas de ponta a ponta. Sem a chave, os testes `live_gemini` ficam em `skip` e o relatório declara "não verificado ao vivo".

**Fase 5: Frontend.** Cinco páginas Streamlit conforme a tarefa, chamando só a API. Validação: `streamlit run app/frontend/Home.py` iniciado, `GET /_stcore/health` retorna `ok`; teste de API que alimenta cada página; captura de tela de cada página quando houver navegador disponível, senão declarar. As páginas Semantic Catalog, Data Quality, SQL & Evidence e Data Overview funcionam sem chave Gemini.

**Fase 6: Validation.** Suíte completa `pytest`; segurança (credenciais, logs sem chave, SQL injection); desempenho (p95 de `query_metric` registrado); `docker compose config` só se Docker existir (senão declarado não verificado); README em português com instalação, carga, configuração do Gemini e roteiro de demonstração; relatório final com critérios de aceite 1 a 12 marcados como verificado por execução ou não, com comandos e saídas.

## 15. Testabilidade

| Camada | Teste unitário | Teste de integração |
|---|---|---|
| Validação de entrada | Sim, sem banco | n/a |
| SQL builder | Sim: saída esperada e parâmetros | n/a |
| Query Engine | Parcial | Sim, contra `analytics.duckdb` real populado |
| Geradores | Sim: determinismo por seed | Sim: carga e idempotência no PostgreSQL |
| Regras de qualidade | n/a | Sim, em `oltp` e `dq_lab` |
| Sync e Cosmos | Montagem de registros | Sim: `validate_graph`, MCP em subprocesso, spike do gateway |
| Orquestração do Gemini | Sim, com modelo roteirizado (declarado como não-Gemini) | `live_gemini` com chave |
| API | Sim, `TestClient` | Sim, com bancos reais |
| Streamlit | Funções de formatação | Leitura da API |

## 16. Riscos aceitos

- API do runtime do Cosmos em Developer Preview, incluindo o uso da API interna `store.transition_episode`. Mitigação: pin por commit e `tests/integration/test_cosmos_contract.py`.
- Versões das dependências resolvidas, mas não instaladas. Mitigação: Fase 2 instala e congela.
- Docker: não havia no ambiente desta fase; o Compose foi verificado por execução depois (ver ACCEPTANCE_REPORT, critério 12).
- Gemini sem chave: critérios 5 e 6 dependem de execução futura.
- Sem autenticação de usuário: `user_id` vem de cabeçalho e é registrado; declarado no README.
- Perguntas dos usuários ficam em texto claro no SQLite do Cosmos e em `audit.chat_turn`; sem filtro de dados pessoais.
- `connection.interrupt()` do DuckDB 2.0.1 em conexão `read_only` não foi verificado (pacote ainda não instalado). Teste na Fase 3 (seção 14).

## 17. Respostas à revisão do design

| # | Severidade | Decisão | Onde |
|---|---|---|---|
| 1 | HIGH | Corrigido. Nó `capability` com `resources` ExternalLocator `{system:"poc-tools", uri:"tool:<nome>"}` e `grantee_refs`, validado por `validate_graph` e usado no gateway em `scripts/spikes/spike_capability_graph.py` (saída em `docs/evidence/phase1/`). Mapeamento `uri == resource_ref` explícito | 5.2, 5.3, 3, Discovery 5.10 |
| 2 | MEDIUM | Corrigido. Rótulo reescrito; `ExternalSystemAdapter` documentado e a escolha por `ToolAdapter` justificada | 2, 3, 5.3, Discovery 6 item 23 |
| 3 | MEDIUM | Corrigido em parte. ROADMAP, CAPABILITIES, VERSIONING, FAILURE-MODES e `docs/versions/COSMOS-1.6*.md` lidos ou consultados por busca; nenhum rótulo mudou. Não existe `RELEASE_NOTES` no clone. Não li `docs/verification/COSMOS-1.6-P7.06-VERSION-CLOSEOUT.md` nem os critérios de cada tarefa do 1.6 linha a linha; justificativa: o projeto consome o Cosmos e não o altera | Discovery 1 |
| 4 | MEDIUM | Corrigido. Scripts em `scripts/spikes/`, saídas em `docs/evidence/phase1/`, critério da Fase 1 refeito | Discovery 9, 14 |
| 5 | MEDIUM | Corrigido. Sequência ordenada de chamadas, ids de actor, ciclo do episódio, `transition_episode` declarada como API interna com teste de contrato, tabela de falhas com fail closed (`cosmos_runtime_unavailable`). Escolhi um único actor `poc.user` em vez de um por `user_id`, porque o grafo só é escrito pelo sync e o `user_id` real fica na auditoria | 5.3 |
| 6 | MEDIUM | Corrigido. `date_to` é o `as_of`, `date_from` rejeitado, janela `[as_of-89, as_of]` | 6 |
| 7 | MEDIUM | Corrigido. Série completa antes do filtro de data, calendário com meses zerados, `order_by` e `limit` depois; teste com janela exigido | 6, 14 |
| 8 | MEDIUM | Corrigido. Matriz 8×9 e regra para `date`, `month`, `year` no documento | 6 |
| 9 | MEDIUM | Corrigido. Tabela de validação com tipos, limites e códigos; posse de `query_id` por `user_id`. `X-User-Id` inválido gera 400 em vez de cair em `demo` | 6.1, 9 |
| 10 | MEDIUM | Corrigido. World em volume `/world`, init com `git init` + commit + `cosmos init`; marcado NÃO verificado. Provado localmente que o `init` falha sem `.git` e sem commit | 11, Discovery 5.3 |
| 11 | NIT | Corrigido. Linhas separadas e rótulos distintos | 3, Discovery 6 |
| 12 | NIT | Corrigido. Caminhos `tests/integration/test_cosmos_sync.py` e `test_cosmos_contract.py` em todos os documentos | 5.2, 14, Discovery 9 |
| 13 | NIT | Corrigido. Cita `store.py:37` (WAL) | 5.3 |
| 14 | NIT | Corrigido. Valor `gemini-2.5-flash`, marcado como não verificado, e erro `gemini_model_invalid` | 5.1 |
| 15 | NIT | Corrigido. Declarado em 5.3, 9 e 16; o README repete | 5.3, 9, 16 |

Itens "não verificados" do relatório de revisão: `connection.interrupt()` no DuckDB (teste na Fase 3, risco registrado na seção 16), versões das dependências (Fase 2 instala e congela) e Docker Compose (declarado).

## 18. Respostas à revisão do design (rodada 2)

| # | Severidade | Decisão | Onde |
|---|---|---|---|
| 1 | HIGH | Corrigido. `/tools/{name}` usa `idempotency_key=f"tool:{uuid4()}"`; `created=False` vira erro interno; teste de contrato chama a mesma ferramenta duas vezes | 5.3, 14 |
| 2 | HIGH | Corrigido, opção (a). `chat_turn` entra com `status='started'`; `UPDATE` por coluna e gatilho de transição única; `query_audit` segue só inserção; teste de segurança ampliado | 8, 9 |
| 3 | MEDIUM | Corrigido por execução. `cosmos_explain` e `cosmos_path` executados no World descartável do `proto_sync.py`; saída em `docs/evidence/phase1/mcp_explain.out`. Prova sobre o grafo do sync real fica para `test_cosmos_sync.py` | 3, Discovery 5.7 |
| 4 | MEDIUM | Corrigido. Manifesto não é versionado; `bootstrap.sh` roda `cosmos init`; sync sai com código 2 `world_not_initialized` e nunca cria o World | 5.2, 5.3, 13 |
| 5 | MEDIUM | Corrigido. Marcador `extensions["poc.sync"].owner == "semantic-sync"`, remoção e regravação do conjunto próprio; teste de remoção de ferramenta | 5.2 |
| 6 | MEDIUM | Corrigido. Lock só sobre operações do store; ordem autorizar, consultar, registrar; handler devolve só resumo; endpoints `def` síncronos; teste de `/health` | 5.3, 14 |
| 7 | MEDIUM | Corrigido. Tabela código → HTTP (400, 403, 404, 409, 422, 500, 503, 504) | 6.1 |
| 8 | MEDIUM | Corrigido. `etl_meta` dentro do DuckDB, lida por requisição; cache categórico por `etl_run_id`; teste com dois ETLs | 6, 9 |
| 9 | NIT | Corrigido. Coluna "Rótulo" na Discovery §4; itens 23 e 24 como UNPROVEN com a busca nomeada | Discovery 4, 6 |
| 10 | NIT | Corrigido. Três arquivos movidos para "Lidos parcialmente" | Discovery 1 |
| 11 | NIT | Corrigido. Só `str` é truncada; handler devolve resumo compacto | Discovery 5.9, 4, 5.3 |
| 12 | NIT | Corrigido. Teste obtém nós por `id` e compara `aliases` | 5.2 |

## 19. Respostas à revisão do design (rodada 3)

| # | Severidade | Decisão | Onde |
|---|---|---|---|
| 1 | MEDIUM | Corrigido e provado. `query_id` gerado antes de `new_attempt` e incluído em `parameters`; resumo em `ToolExecutor.pending[query_id]`; handler faz `pop` e levanta `AdapterBoundaryError` se faltar; `ToolAdapter.execute` roda para toda chamada autorizada (inclusive `rejected` e `error`), então cada `allow` tem um `adapter.result`. O spike mostra 1 decisão e 1 `adapter.result` para `unknown_metric`, o Query Engine stub rodando uma vez e `pending` vazio no fim | 5.3 passo 3, 14; `docs/evidence/phase1/spike_toolexecutor_handoff.out` |
| 2 | MEDIUM | Corrigido e provado. Ordem: esquema Pydantic, depois `new_attempt`/`authorize_effect`, depois domínio e execução. `invalid_arguments` não abre tentativa, grava `rejected` com `cosmos_decision_id` nulo; coluna aceita `NULL` (também para `unknown_tool`). Spike: campo extra não abre episódio nem decisão; chamada negada não executa o motor | 5.3, 6.1, 9 |
| 3 | MEDIUM | Corrigido e provado, exceto o grafo real. `SemanticReader` usa caminho explícito, sem `load_graph`; novo código `semantic_catalog_unavailable` (503) na tabela de falhas, na tabela de HTTP e no lifespan; `"error" in resultado` de `tool_explain` vira `internal_error`; teste do MCP com `COSMOS_GRAPH` e `cwd` fixos e `count > 0`. O spike cobre grafo ausente, ilegível, vazio e sem `poc.metric`. **Não provado:** comportamento sobre o grafo do sync real (Fase 3) | 5.5, 5.2, 5.3, 6.1 |
| 4 | NIT | Corrigido (texto). ETL com duas conexões: `poc_reader` extrai, `poc_loader` grava `ops.etl_run`; reconciliação com `poc_reader` e `poc_dq`. Sem execução: depende das migrações da Fase 2 | 8, 14 |
| 5 | NIT | Corrigido. Famílias travadas; versões provisórias até o congelamento da Fase 2. `pydantic==2.14.4` instalado e verificado no `.venv`; as demais continuam não instaladas | 12 |
| 6 | NIT | Corrigido (texto e teste planejado). Restrição de nomes `tools` e `runtime` em §13 | 13 |

## 20. Respostas à revisão do design (rodada 4)

| # | Severidade | Decisão | Onde |
|---|---|---|---|
| 1 | MEDIUM | Corrigido e provado. Regra única em 6.1: falha de esquema (tipo, campo extra, tamanho, UUID, regex de `metric`) é sempre `invalid_arguments` (400), antes do gateway, sem `new_attempt` e com `cosmos_decision_id` nulo. `invalid_query` e `invalid_query_id` removidos. `unknown_metric` (422) só vale para formato válido e ausente do catálogo, depois do `allow`. `query_not_found` e `no_sql_available` seguem como domínio. Lista de `rejected` e testes de contrato ajustados. Spike: `query_id="abc"`, `query=""` e `metric="X-1"` geram `invalid_arguments` sem evento Cosmos; `unknown_metric` gera 1 decisão e 1 `adapter.result` | 6.1, 5.3 passo 3; `docs/evidence/phase1/spike_toolexecutor_handoff.out` |
| 2 | NIT | Corrigido. `spike_toolexecutor_handoff.py` entra na lista de §13 e na validação da Fase 1 (§14), com saída esperada `OK` e caminho da evidência | 13, 14 |
| 3 | NIT | Aceito sem mudança de design. O spike usa Query Engine stub e o grafo do sync real não foi lido. Ação: o relatório da Fase 3 em `docs/history/PHASE_REPORTS.md` deve marcar "comportamento do `SemanticReader` e de `explain_metric` sobre o grafo do sync real" como verificado ou não verificado, com a saída de `test_cosmos_sync.py` e `test_cosmos_contract.py` | 5.5, 14 |
