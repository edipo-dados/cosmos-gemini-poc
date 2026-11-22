# Descoberta do Cosmos (Fase 1)

Data da execução: ambiente descrito em `docs/history/ENV_CHECK.md` (macOS arm64, Python 3.11.18 em `.venv`, Docker ausente, `GEMINI_API_KEY` ausente).

Repositório lido: `https://github.com/cosmos-semantic/cosmos`, clonado em `.vendor/cosmos` (pasta ignorada pelo git do projeto).
Commit: `464175f6bfa641c30f0b2cdeb0ef84269fd202cb` (`v1.6.0-preview-1-g464175f`). `pyproject.toml`: `cosmos-platform 1.6.0.dev1`, `requires-python >=3.10`, dependência única `jsonschema>=4.0.0`.

Legenda dos rótulos:

- **PROVEN**: executei o comando ou código neste ambiente e a saída está registrada abaixo.
- **DOCUMENTED-ONLY**: descrito em arquivo do Cosmos, mas não executei.
- **UNPROVEN**: não encontrei documentação suficiente ou a execução não demonstrou o comportamento. Não pode ser usado como premissa.

Os caminhos citados são relativos a `.vendor/cosmos/`.

## 1. Arquivos lidos

Lidos integralmente: `AGENTS.md`, `README.md`, `docs/OPERATOR-GUIDE.md`, `runtime/README.md`, `docs/QUICKSTART.md`, `docs/CAPABILITIES.md` (179 linhas, seções 1 a 9.3, segunda leitura completa após a revisão), `spec/ontology/KNOWLEDGE.md`, `spec/ontology/CAPABILITY.md`, `spec/ontology/NODE.md`, `tools/cosmos_mcp_server.py`, `pyproject.toml`.

Lidos na revisão (complemento): `docs/ROADMAP.md` (477 linhas, agora inteiro: workstreams P0 a P7 do 1.6 concluídos, 1.6 fechado em 2026-09-06 como **Developer Preview**, tag `cosmos-v1.6.0-preview`; 1.6.x "Productization & Visibility" em andamento), `docs/versions/COSMOS-1.6.md` (661 linhas: decisão executiva, arquitetura-alvo, fronteiras de propriedade, níveis de suporte e títulos das tarefas P0 a P7; os critérios de cada tarefa foram consultados por busca, não linha a linha), `docs/versions/COSMOS-1.6.x-PRODUCTIZATION.md` e `docs/versions/COSMOS-1.6.x-VISIBILITY-EXECUTION.md` (busca por MCP, `ToolAdapter`, `AuthorizationGateway`, SQLite, Python), `docs/VERSIONING.md` (114 linhas), `docs/FAILURE-MODES.md` (350 linhas; catálogo FM-01 a FM-16, lidos FM-01 a FM-03, FM-09 e FM-14 e os títulos dos demais). Não há arquivo `RELEASE_NOTES_*` no clone (`find . -iname '*release*'` só devolve `releases/cosmos-1.5`, ferramentas de assinatura e documentos em `docs/verification/`). O fechamento do 1.6 está em `docs/verification/COSMOS-1.6-P7.06-VERSION-CLOSEOUT.md`, que **não** li.

Efeito da leitura complementar nos rótulos: nenhum rótulo mudou. Confirmações: (a) o 1.6 é **Developer Preview**, o que reforça o pin por commit e o teste de contrato para a API de runtime; (b) o MCP somente leitura continua `PENDING` em `docs/CAPABILITIES.md` §7 (rótulo "suporte oficial UNPROVEN" mantido); (c) a arquitetura-alvo do 1.6 coloca `AuthorizationGateway` e "scoped adapters" no Effect Broker, coerente com o uso de `ToolAdapter`; (d) FM-14 ("External-authority capture") e FM-06/FM-08 (autoridade duplicada, deriva semântica silenciosa) justificam duas decisões do POC: os números vêm dos bancos e não do Cosmos, e o YAML é a fonte de verdade com teste que compara YAML e grafo.

Lidos parcialmente: `docs/ARCHITECTURE.md` (até a seção "Execution runtime"), `docs/UNIVERSE-AND-WORLD-MODEL.md` (até "Observatory naming"), `spec/execution-stack/MODEL-GATEWAY-CONTRACT.md` (até "Required negative conformance cases"), `docs/SYSTEM-BOUNDARY.md` (apenas trechos por grep), `spec/ontology/IDENTITY-AND-REFERENCES.md` e `spec/ontology/RELATION-TYPES.md` (início), `tools/cosmos.py` (parser de comandos), `tools/cosmos_capture_hook.py` (cabeçalho), `runtime/cosmos_runtime/{actors,effects,authorization}.py` (classes e métodos citados).

Não lidos: `docs/ORIGINAL-PLAN.md`, `docs/VISION.md`, `docs/PRINCIPLES.md`, `docs/TERMINOLOGY.md`, `docs/EXECUTION-PROTOCOL.md`, `docs/TRUST-AND-ASSURANCE-MANDATE.md`, `docs/phases/*`, `docs/verification/*`. O `AGENTS.md` do Cosmos pede essa leitura para quem modifica o Cosmos. Este projeto apenas consome o Cosmos e não altera o repositório dele, então não li esses arquivos. Isso é uma limitação desta descoberta.

## 2. Arquitetura do Cosmos

Fontes: `README.md`, `docs/ARCHITECTURE.md`, `runtime/README.md`, `docs/SYSTEM-BOUNDARY.md`.

- O Cosmos se descreve como "Semantic Operating Environment for Interchangeable Intelligence". Ele **não é** um agente, um modelo, um banco de dados analítico nem uma camada semântica SQL (`README.md`: "Cosmos is not another coding agent"). A equação central é `Intelligence = Model + Bound Context + Capabilities + Current Objective` (`README.md`, `docs/ARCHITECTURE.md`).
- Doutrina tripartite (`README.md`, `AGENTS.md`): **Ambiente** (Cosmos: memória durável, verdade de referência, envelopes de capacidade), **Harness** (a ferramenta que executa processos e I/O) e **Modelo** (raciocínio efêmero, por exemplo Gemini). Frase do projeto: "Cosmos persists. The model reasons. The harness bridges."
- Camadas (`docs/ARCHITECTURE.md`): ambiente semântico durável; grafo semântico (nós, arestas, artefatos, eventos, tarefas, capacidades, conhecimento, context bundles, sessões, atores); context binding; inteligência (modelos); fronteira de capacidades; runtime de execução.
- Fluxo do runtime (`runtime/README.md`): objetivo → Task e ExecutionPackage duráveis → ContextBundle e Binding Record → roteamento de Actor/modelo → Capability Envelope derivado → AttemptedEffect autorizado → adaptador com escopo → PerformedEffect, Artifact, Event e evidência → decisão de conclusão independente → candidatos a aprendizado.
- Persistência de execução: SQLite (`runtime/README.md`, "Durable state"). Tabelas observadas por mim: `runtime_tasks`, `execution_packages`, `runtime_episodes`, `runtime_bindings`, `runtime_events`, `runtime_checkpoints`, `runtime_idempotency`. O README diz que SQLite é "an implementation baseline, not a Cosmos semantic invariant".
- Não há `Dockerfile` nem `docker-compose*` no repositório (`find . -iname 'Dockerfile*' -o -iname 'docker-compose*'` retornou vazio). O Cosmos é um pacote Python mais arquivos locais. Não existe "serviço Cosmos" documentado para o Compose.

## 3. Conceito de World

Fontes: `docs/UNIVERSE-AND-WORLD-MODEL.md`, `docs/OPERATOR-GUIDE.md`.

- **World** é "one durable Cosmos environment/instance with its own semantic graph, authority/provenance state, tasks, knowledge, artifacts, relationships, and runtime continuity". Um World pode referenciar sistemas externos sem se tornar autoridade sobre eles.
- Famílias: Personal, Developer e Company Cosmos. "Universe" e "All Worlds" são apenas visões agregadas. "Cosmos Prime" é o World de autoconstrução do próprio Cosmos.
- Na prática, um World é um repositório Git com `cosmos.environment.json` e a pasta `.cosmos/` (`graph.json`, `first-inspection.json`, `actor-scripts.json`, `learning.json`, `runtime.sqlite3`) (`docs/OPERATOR-GUIDE.md`, "Quick Start").
- **Decisão para o POC**: o World deste projeto é "Developer Cosmos" ligado ao repositório `poc-cosmos`. O `cosmos init` resolve o diretório raiz do git (ver 5.3), então o World fica na raiz do repositório e não em `cosmos/worlds/`.

## 4. Pontos de integração (o que o Cosmos oferece)

| Tema | Mecanismo no Cosmos | Rótulo | Citação |
|---|---|---|---|
| Persistir contexto e conhecimento semântico | Registros JSON no `.cosmos/graph.json`: nós (`entity`, `knowledge`, `artifact`, `actor`, `capability`, ...) e arestas (`core.governed_by`, ...), validados por `schemas/cosmos-record.schema.json`. Conhecimento tem `knowledge_class` (`decision`, `policy`, `rule`, `convention`, `claim`, `lesson`, `reference`) e `lifecycle_state` | PROVEN (5.6) | `spec/ontology/KNOWLEDGE.md`, `spec/ontology/NODE.md`, `spec/ontology/RELATION-TYPES.md` |
| Proveniência | Bloco `provenance` obrigatório em todo registro; arestas `core.supports`, `core.references`; eventos de runtime em SQLite | PROVEN para o bloco `provenance` validado (5.6) e eventos SQLite (5.9); DOCUMENTED-ONLY para `core.supports` e `core.references` | `spec/ontology/IDENTITY-AND-REFERENCES.md`, `runtime/README.md` |
| Registrar capacidades | Nó `capability` com `action`, `decision` (`allow`, `deny`, `approval_required`), `grantee_refs`, `resources`. O nó é autoridade semântica e "does not itself enforce the effect" | PROVEN (5.10) | `spec/ontology/CAPABILITY.md` |
| Registrar ferramentas executáveis | `ToolAdapter.register(tool_ref, handler)` e execução só com `AuthorizedEffect` para a ação `tool.invoke` | PROVEN (5.9) | `runtime/cosmos_runtime/effects.py` (classe `ToolAdapter`), `runtime/README.md` ("Execute through scoped adapters") |
| Autorização | `AuthorizationGateway.new_attempt(...)` e `authorize_effect(...)`; negar por padrão; `AuthorizationBlocked` quando negado | PROVEN (5.9) | `runtime/cosmos_runtime/authorization.py`, `runtime/README.md` ("Derive and enforce authority") |
| Conectar agentes externos | Leitura de `AGENTS.md` e `@.cosmos/graph.json` por harnesses; servidor MCP somente leitura sobre `graph.json` | PROVEN para o servidor MCP (5.7); DOCUMENTED-ONLY para leitura de `AGENTS.md` por harnesses | `AGENTS.md`, `docs/QUICKSTART.md`, `tools/cosmos_mcp_server.py` |
| Integrar modelos externos | `ActorAdapter` (`profile()`, `invoke()`), `OpenAICompatibleActorAdapter` (endpoint de chat completions), `ModelRouter`; contrato de gateway `cosmos.model-gateway/1` | DOCUMENTED-ONLY | `runtime/README.md` ("Route interchangeable intelligence"), `runtime/cosmos_runtime/actors.py`, `spec/execution-stack/MODEL-GATEWAY-CONTRACT.md` |
| Ler o mundo | CLI `cosmos init/open/status/validate/doctor/delta/report` | PROVEN para `init`, `validate`, `status` (5.3, 5.4); DOCUMENTED-ONLY para `open`, `delta`, `report`; `doctor` PROVEN que falha aqui | `docs/OPERATOR-GUIDE.md`, `tools/cosmos.py` |

Regras do Cosmos que condicionam o projeto:

- IDs devem ser `cosmos:<uuidv7>`, opacos e imutáveis (`spec/ontology/IDENTITY-AND-REFERENCES.md`). O helper `stable_cosmos_ref(semantic_key)` em `tools/reference_repository_projection.py` gera IDs UUIDv7 determinísticos a partir de uma chave semântica.
- Campos desconhecidos no nível raiz são rejeitados; extensões vão em `extensions` com chaves namespaced (`spec/ontology/SERIALIZATION.md`, regra 3).
- Segredos não devem virar conhecimento semântico (`docs/SYSTEM-BOUNDARY.md`, linha 85; `docs/OPERATOR-GUIDE.md`, "What not to do").
- Observar dados externos não torna o Cosmos a fonte de verdade deles (`docs/SYSTEM-BOUNDARY.md`, linha 163). Para o POC: os bancos continuam sendo a fonte dos números; o Cosmos guarda significado, regras e proveniência.
- O Cosmos 1.5 diz que não se deve assumir que ele "magically inject itself" em harnesses externos; a integração precisa ser comprovada empiricamente (`docs/OPERATOR-GUIDE.md`, "Harness-first use").

## 5. Execuções (comandos e saídas)

Os experimentos 5.3 a 5.10 rodaram em repositórios descartáveis em `/tmp` (criados com `git init`), para não escrever no repositório do projeto. Os scripts e as saídas estão no repositório (seção 9). O `cosmos init` do repositório real fica para a Fase 3.

### 5.1 Clone

```bash
git clone https://github.com/cosmos-semantic/cosmos .vendor/cosmos
git -C .vendor/cosmos log --oneline | head -1   # 464175f fix(packaging): declare jsonschema dependency, ...
git -C .vendor/cosmos describe --tags           # v1.6.0-preview-1-g464175f
```

Resultado: clone concluído (PROVEN).

### 5.2 Instalação

```bash
export PATH="$HOME/Library/Python/3.9/bin:$PATH"
uv pip install --python .venv/bin/python -e .vendor/cosmos
```

Saída resumida:

```text
Resolved 7 packages in 695ms
 Built cosmos-platform @ file:///Users/edipo/projetos/poc-cosmos/.vendor/cosmos
Installed 7 packages
 + attrs==26.1.0
 + cosmos-platform==1.6.0.dev1 (from file:///.../.vendor/cosmos)
 + jsonschema==4.26.0
 + jsonschema-specifications==2025.9.1
 + referencing==0.37.0
 + rpds-py==2026.9.1
 + typing-extensions==4.16.0
```

O instalador `curl ... | sh` e `pip install cosmos-platform` (PyPI) **não foram executados**. A versão publicada no PyPI não foi verificada. O pin do projeto usa o commit do GitHub (ver `../ARCHITECTURE.md`, seção 12).

### 5.3 `cosmos init`

```bash
mkdir /tmp/cosmos-scratch/w && cd /tmp/cosmos-scratch/w && git init -q && echo "# t" > README.md \
  && git add . && git commit -qm init
/Users/edipo/projetos/poc-cosmos/.venv/bin/cosmos init .
```

```text
[init] Cosmos 1.6 onboarding for w
[init] environment_id: cosmos:environment:developer:w
[init] first_read_path: README.md
[init] writing .githooks/{post-commit,post-checkout,post-merge} …
[init] live-read -> /private/tmp/cosmos-scratch/w/.cosmos/runtime.sqlite3 …
[OK] Cosmos is active for w
     Studio:      http://127.0.0.1:8766/  (cosmos open /private/tmp/cosmos-scratch/w)
     Observatory:  http://127.0.0.1:7777/  (cosmos open /private/tmp/cosmos-scratch/w --observatory)
```

Arquivos criados: `cosmos.environment.json`, `.cosmos/{graph.json, first-inspection.json, actor-scripts.json, learning.json, runtime.sqlite3}`, `.githooks/{post-commit,post-checkout,post-merge}`. O grafo inicial tem 6 registros (1 actor, 1 entity `core.project`, 1 artifact `software.source_tree`, 1 knowledge `rule` "Repository Authority Rule", 2 arestas).

Achados:

1. `cosmos init some/subdir` dentro de um repositório resolveu a raiz do git (`project root: /private/tmp/cosmos-scratch/w`). O World fica sempre na raiz do repositório.
2. `cosmos init` exige repositório git com commit (PROVEN nesta revisão): em diretório sem `.git`, terminou com `ValueError: Cosmos 1.5 bootstrap requires an existing Git repository`; com `git init` e sem commit, falhou em `git rev-parse HEAD` (`CalledProcessError`, status 128) e não criou `.cosmos/`. Com ao menos um commit, funciona. Com `cosmos.environment.json` e `graph.json` já presentes, o `init` pula o bootstrap (`tools/cosmos.py`, "bootstrap skipped"), então é idempotente.
3. Os hooks gerados contêm um caminho fixo de Windows: `exec py -3.12 "C:/Users/Harvey/Cosmos/tools/cosmos_capture_hook.py" --repo "$PROJECT_ROOT" "$@"`. Eles não funcionam no macOS. `git config core.hooksPath` não foi alterado, então os hooks ficam inativos. **Decisão**: o projeto não ativa esses hooks e não os versiona.

### 5.4 `cosmos status`, `validate`, `doctor`

```bash
cosmos status .    # "pack_valid": true, "world_initialized": true, "node_count": 4, "frozen_core_intact": false, "hook_status": {"status": "none"}
cosmos validate .  # "valid": true, "node_count": 4, "edge_count": 2
cosmos doctor . --quick
```

`doctor` retornou `"verdict": "FAIL"`: `gate:build` falhou com `command not found: pnpm` e `hook-status.json not found`. `frozen_core_intact: false` porque o pacote foi instalado a partir de um clone e não há baseline 1.5 congelado. Nenhum dos dois é bloqueante para o POC. **Decisão**: usar `cosmos validate` e `tools.validate_ontology.validate_graph` como verificações, e não usar `doctor`.

### 5.5 Runtime e validações do próprio Cosmos

```bash
.venv/bin/python -m runtime.cosmos_runtime health --db /tmp/cosmos-scratch/rt.sqlite3
# {"database_path": "/tmp/cosmos-scratch/rt.sqlite3", "environment_ref": "cosmos:local", "runtime": "cosmos", "sqlite_version": "3.53.1", "status": "ok", "store": "sqlite"}

cd .vendor/cosmos
../../.venv/bin/python tools/validate_ontology.py
# PASS: 3 fixtures validate against Cosmos record schema and cross-record integrity checks
../../.venv/bin/python -m unittest runtime.tests.test_foundation runtime.tests.test_context_binding
# Ran 15 tests ... OK
```

Python 3.11.18 foi suficiente. Os documentos dizem que 3.12 é a versão testada (`runtime/README.md`, "Operational assumptions"); não rodei a suíte completa. `docs/CAPABILITIES.md` informa 117 testes não passando por causa de ambiente (Windows e árvore suja); não reproduzi esse número.

### 5.6 Escrita de conhecimento semântico no `graph.json`

Não encontrei na documentação um comando ou API de "importar definições semânticas". O que existe e é documentado: o formato dos registros, o esquema JSON e o validador `tools.validate_ontology.validate_graph(list_or_path) -> list[str]`. O gancho de captura do próprio Cosmos (`tools/cosmos_capture_hook.py`) escreve em `.cosmos/graph.json` de forma atômica (arquivo temporário e `os.replace`), valida antes de escrever e é idempotente. Ele grava eventos de commit, não conhecimento.

Executei um protótipo que monta registros no formato do Cosmos e valida com o validador do próprio Cosmos antes de gravar. Resumo do código (entity `poc.metric` com `extensions`, knowledge `rule` com `scope_refs`, aresta `core.governed_by`, capability `metric.query`):

```python
from tools.validate_ontology import validate_graph
from tools.reference_repository_projection import stable_cosmos_ref
m = node("metric:net_revenue", node_type="entity", schema="cosmos.node/1", entity_type="poc.metric",
         display_name="net_revenue", description="Receita liquida", aliases=["Faturamento liquido"],
         extensions={"poc.metric": {"formula": "gross - refunds", "version": "1.0.0"}})
k = node("rule:net_revenue", node_type="knowledge", schema="cosmos.knowledge/1", knowledge_class="rule",
         lifecycle_state="active", statement="net_revenue = sum(paid orders) - sum(effective refunds)",
         scope_refs=[m["id"]])
e = {... "relation_type": "core.governed_by", "source": m["id"], "target": k["id"]}
c = node("cap:query_metric", node_type="capability", schema="cosmos.capability/1", action="metric.query",
         decision="allow", grantee_refs=[actor], resources=[{"system": "duckdb", "uri": "duckdb://analytics.duckdb"}])
print("errors:", validate_graph(new))
```

Saída: `errors: []`. Depois `cosmos validate .` retornou `"valid": true, "node_count": 7, "edge_count": 3`.

Conclusão: **o formato e a validação são PROVEN**. A escrita é feita por um script nosso e não por uma API oficial de ingestão. O Cosmos documenta que aprendizado candidato passa por Candidate Intake e portão de admissão (`runtime/README.md`, "Hand completed work to learning/maintenance"; `docs/CAPABILITIES.md`, "Candidate learning admission gate"). Nosso sync grava nós já com `lifecycle_state: active` e `authority.class: cosmos`, como o `cosmos init` faz com a "Repository Authority Rule", e portanto **contorna esse fluxo de admissão**. Essa escolha é do projeto, não do Cosmos, e deve ser dita no README.

### 5.7 Servidor MCP (somente leitura)

`tools/cosmos_mcp_server.py` é um servidor JSON-RPC 2.0 por stdio, sem dependência do pacote `mcp`. Ele lê o grafo de `$COSMOS_GRAPH`, `./.cosmos/graph.json` (subindo diretórios) ou da raiz do Cosmos.

```bash
cd /tmp/cosmos-scratch/w
printf '%s\n' \
 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
 '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
 '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"cosmos_query","arguments":{"where":{"display_name":"net_revenue"}}}}' \
 '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"cosmos_tool","arguments":{}}}' \
 '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"cosmos_act","arguments":{}}}' \
 | /Users/edipo/projetos/poc-cosmos/.venv/bin/python /Users/edipo/projetos/poc-cosmos/.vendor/cosmos/tools/cosmos_mcp_server.py
```

Resultados observados:

- `initialize`: `serverInfo {"name":"cosmos-mcp-server","version":"1.5.0"}`, `protocolVersion "2024-11-05"`.
- `tools/list`: 6 ferramentas: `cosmos_open`, `cosmos_query`, `cosmos_path`, `cosmos_tool`, `cosmos_act`, `cosmos_explain`.
- `cosmos_query` com `display_name: "net_revenue"`: `count: 2`, o nó `entity` e o nó `knowledge` (busca por substring no `display_name`, sem diferenciar maiúsculas).
- `cosmos_tool`: `count: 1`, o nó de capability inserido.
- `cosmos_act`: `isError: true` ("is not exposed by the read-only Cosmos MCP server").
- `cosmos_explain` e `cosmos_path` (executados depois, no World descartável preparado por `scripts/spikes/proto_sync.py`): `cosmos_explain {"id": <id de net_revenue>}` devolveu o nó, 1 aresta de saída `core.governed_by` e 1 vizinho `knowledge` com `knowledge_class: rule`. `cosmos_path {"from": <id>, "relation": "descendants", "relation_type": "core.governed_by"}` devolveu a mesma aresta. Ambos com `isError: false`. Saída em `docs/evidence/phase1/mcp_explain.out`. Ainda não provado: o mesmo resultado sobre o grafo gerado pelo sync real (Fase 3, `test_cosmos_sync.py`).

Limitações verificadas no código (`tools/cosmos_mcp_server.py`, função `tool_query`):

- Só filtra por `id`, `node_type`, `record_type`, `schema`, e substring em `display_name`, `summary`, `statement`, `description`. **Não busca em `aliases`**. Chaves desconhecidas são ignoradas silenciosamente (um filtro por `entity_type` não filtra nada).
- `cosmos_open` clona repositórios Git remotos para `~/.cosmos/workspaces`. Não é usado e **não deve ser exposto ao agente** (acesso de rede e escrita em disco).
- Divergência de documentação: `docs/CAPABILITIES.md` (seção 7) lista "Read-only MCP query server" como `PENDING`, mas o código existe e respondeu. O rótulo do projeto é PROVEN para execução e UNPROVEN para "suporte oficial".
- Nenhuma das 6 ferramentas tem o nome das 7 ferramentas do POC.

### 5.8 Context binding sobre o nosso conhecimento

```bash
cd .vendor/cosmos
../../.venv/bin/python -m tools.cosmos15_operator live-read /tmp/cosmos-scratch/w/cosmos.environment.json \
  --db /tmp/cosmos-scratch/w/.cosmos/runtime.sqlite3
```

Saída relevante (com os nós de métrica já no grafo):

```text
"selected_context_refs": ["cosmos:01a05cd7-2a00-7872-8b1e-24fbfbcf9a8a"],   # só a Repository Authority Rule
"state": "completed", "verified_complete": true
```

O binder escolheu só a regra do repositório. Os nós de métrica **não** foram incluídos no ContextBundle desse caso, porque o caso (`first-inspection.json`) tem outro objetivo e outras âncoras. Isso **não prova** que o binder nativo recupera nossas métricas para uma pergunta analítica. Rótulo: UNPROVEN. Eventos de runtime gravados (`runtime_events`): `runtime.task.intake`, `runtime.episode.created`, `runtime.context.bound`, `runtime.authorization.envelope`, `runtime.authorization.decision`, `runtime.adapter.result`, `runtime.effect.performed`, `runtime.evidence.recorded`, `runtime.execution.summary`, `runtime.actor.response` (PROVEN, para o caso padrão de leitura do README).

### 5.9 Registrar ferramenta e autorizar por capacidade (spike)

O projeto precisa que as 7 ferramentas do agente passem por algo do Cosmos além de leitura do grafo. A documentação aponta `ToolAdapter` e `AuthorizationGateway`. Montei um spike com o padrão de `runtime/tests/test_sandbox_adapters.py`: criar serviços com SQLite, receber um objetivo (`intake_objective`), levar o episódio a `READY`, conceder uma capacidade `tool.invoke` somente para `tool:list_metrics`, registrar dois handlers e tentar invocar ambos.

```python
from runtime.cosmos_runtime import (AuthorizationGateway, ObjectiveRequest, RuntimeConfig, ToolAdapter, build_services)
from runtime.cosmos_runtime.authorization import AuthorizationBlocked
from runtime.cosmos_runtime.effects import AdapterBoundaryError
...
gw = AuthorizationGateway(svc, lambda _: state)          # state = {"capabilities": [...], "approvals": [], "delegations": []}
tools = ToolAdapter(svc)
tools.register("tool:list_metrics", lambda p: {"metrics": ["net_revenue"], "args": p})
tools.register("tool:drop_everything", lambda p: "should never run")
eff = gw.new_attempt(episode_id=intake.episode_id, action="tool.invoke", resource_ref=ref, parameters=params)
tok = gw.authorize_effect(eff); out = tools.execute(tok).output
```

Saída:

```text
ALLOWED : ('decision', 'allow', {'metrics': ['net_revenue'], 'args': {'q': 'x'}})
DENIED  : ('blocked', 'AuthorizationBlocked', 'effect not authorized: deny: no_applicable_allow')
[["runtime.adapter.result", 1], ["runtime.authorization.decision", 2], ["runtime.episode.created", 1], ["runtime.task.intake", 1]]
```

Conclusões (PROVEN): o `AuthorizationGateway` nega por padrão uma ferramenta sem capacidade; a ferramenta concedida roda via `ToolAdapter`; cada decisão e cada resultado viram eventos duráveis no SQLite do Cosmos. Cuidados:

- `ToolAdapter._record` aplica `_safe_value` (`runtime/cosmos_runtime/effects.py:58`), que trunca **somente `str`** acima de 2048 caracteres. Um `dict` devolvido pelo handler é gravado inteiro no evento `runtime.adapter.result` em `.cosmos/runtime.sqlite3`. Por isso o handler do projeto devolve apenas um resumo compacto (`query_id`, `row_count`, `status`). O Cosmos não é o repositório de evidências completas; a tabela de auditoria no PostgreSQL (ver `../ARCHITECTURE.md`) guarda o resultado completo.
- Esses nomes (`build_services`, `AuthorizationGateway`, `ToolAdapter`, ...) vêm do código e de `runtime/README.md`, mas o produto se declara "Developer Preview". Não há garantia de estabilidade. O pin por commit mitiga.
- Este spike (`scripts/spikes/spike_tool_gateway.py`) usa `state` montado em memória com `resources` como strings, formato do gateway. O nó `capability` do grafo foi tratado no experimento 5.10.
- `transition_episode` (usado para chegar a `READY`) é método do `SQLiteRuntimeStore`, usado nos testes do Cosmos (`runtime/tests/test_sandbox_adapters.py:47`) e **não** documentado em `runtime/README.md`. É API interna.

Script e saída estão no repositório: `scripts/spikes/spike_tool_gateway.py`, `docs/evidence/phase1/spike_tool_gateway.out`.

### 5.10 Nó `capability` `tool.invoke` do grafo conduzindo o gateway

Respostas à revisão do design. O script `scripts/spikes/spike_capability_graph.py` cria um World descartável (`git init`, commit, `cosmos init`), grava no `graph.json` dois nós `actor` (`poc.agent`, `poc.user`) e um nó `capability` no formato da spec: `action: "tool.invoke"`, `decision: "allow"`, `grantee_refs: [<id do actor poc.agent>]`, `resources: [{"system": "poc-tools", "uri": "tool:list_metrics"}]`. O formato de `ResourceRef` (CosmosRef ou ExternalLocator com `system` e `uri` obrigatórios) vem de `spec/ontology/CAPABILITY.md` e `spec/ontology/IDENTITY-AND-REFERENCES.md`, seção "External locators". Depois valida com `validate_graph`, converte o nó para o estado do `AuthorizationGateway` (`resources` = lista de `uri`, `capability_id` = id do nó, `task_ref` do episódio) e chama o gateway.

```text
validate_graph errors: []
tool:list_metrics -> ('ALLOWED', {'metrics': ['net_revenue']})
tool:query_metric -> ('DENIED', 'AuthorizationBlocked', 'effect not authorized: deny: no_applicable_allow')
tool:list_metrics again (2nd attempt, same episode) -> ('ALLOWED', {'metrics': ['net_revenue']})
final episode state: completed
```

Conclusões (PROVEN): (a) o nó com ExternalLocator e `grantee_refs` é aceito pelo validador do Cosmos; (b) o mapeamento nó → estado do gateway, escrito pelo projeto, faz o gateway permitir a ferramenta com nó e negar a sem nó; (c) um episódio aceita várias tentativas e fecha em `COMPLETED` pela sequência `CREATED → PREPARING → READY → RUNNING → COMPLETED`. Não provado: carga nativa de nós pelo Cosmos (não existe: `AuthorizationGateway._state` só chama o provider) e `READY → FAILED` (está em `ALLOWED_TRANSITIONS`, `runtime/cosmos_runtime/model.py`, sem execução). O protótipo do 5.6 usa a ação `metric.query`; o design não a usa.

Saída gravada em `docs/evidence/phase1/spike_capability_graph.out`.

## 6. Recursos disponíveis na versão atual

| # | Recurso | Rótulo | Evidência / citação |
|---|---|---|---|
| 1 | Instalação editável a partir do clone em Python 3.11 | PROVEN | 5.2 |
| 2 | Instalação por `pip install cosmos-platform` e por `install.sh` | DOCUMENTED-ONLY | `README.md`, "Quickstart". Não executado |
| 3 | `cosmos init` cria World (`cosmos.environment.json`, `.cosmos/*`) | PROVEN | 5.3; `docs/OPERATOR-GUIDE.md` |
| 4 | Git hooks gerados | PROVEN que existem e que apontam para caminho Windows; **inutilizáveis** | 5.3 |
| 5 | `cosmos validate`, `cosmos status` | PROVEN | 5.4 |
| 6 | `cosmos doctor` | PROVEN que falha neste ambiente (pnpm e hook-status ausentes) | 5.4 |
| 7 | Runtime SQLite (`runtime.cosmos_runtime health`) | PROVEN | 5.5; `runtime/README.md` |
| 8 | Esquema de registros e validador (`validate_graph`, `validate_ontology.py`) | PROVEN | 5.5, 5.6; `schemas/cosmos-record.schema.json` |
| 9a | Persistir `entity` (`poc.metric`), `knowledge` (`rule`) e aresta `core.governed_by` no `graph.json` com validação | PROVEN (mecanismo: script próprio + validador do Cosmos) | 5.6; `spec/ontology/*.md`; `docs/evidence/phase1/proto_sync.out` |
| 9b | Persistir nó `capability` `tool.invoke` (ExternalLocator em `resources`, `grantee_refs`) com validação | PROVEN | 5.10 |
| 10 | Fluxo oficial de admissão de conhecimento candidato (Candidate Intake) | DOCUMENTED-ONLY | `runtime/README.md`; `docs/CAPABILITIES.md` §2. Não usado pelo sync |
| 11 | Servidor MCP por stdio, somente leitura (`cosmos_query`, `cosmos_path`, `cosmos_tool`, `cosmos_explain`, `cosmos_act` desabilitada, `cosmos_open`) | PROVEN (execução). Suporte oficial UNPROVEN (`CAPABILITIES.md` diz `PENDING`) | 5.7; `tools/cosmos_mcp_server.py` |
| 12 | Busca por sinônimos (`aliases`) via MCP | UNPROVEN, e o código mostra que não existe | `tool_query` em `tools/cosmos_mcp_server.py` |
| 13 | Context binding nativo de métricas para uma pergunta analítica | UNPROVEN | 5.8 |
| 14 | Binding do caso padrão de leitura do repositório | PROVEN | 5.8; testes `test_foundation` e `test_context_binding` (15 OK) |
| 15 | `ToolAdapter` + `AuthorizationGateway` (permitir e negar por padrão) | PROVEN | 5.9 |
| 16 | Carga **nativa** de nós `capability` do grafo pelo gateway | UNPROVEN, e o código mostra que não existe (o gateway só chama `authority_state_provider`). Mapeamento nó → estado feito pelo projeto: PROVEN | 5.10; `authorization.py` |
| 17 | Eventos duráveis de decisão, resultado e evidência no SQLite | PROVEN | 5.8, 5.9 |
| 18 | `OpenAICompatibleActorAdapter` e `ModelRouter` | DOCUMENTED-ONLY | `runtime/README.md`; `runtime/cosmos_runtime/actors.py`. Não executado |
| 19 | Gemini dentro do Cosmos | UNPROVEN | O único uso de Gemini no Cosmos é o `byom_router.js` do Studio (URL REST `generateContent` do `gemini-2-5-flash`), o catálogo `catalogs/model-modalities.json` e o adaptador de doorway `GEMINI.md` (`tools/cosmos_project_adapters.py`). Nenhum usa `google-genai` |
| 20 | Cosmos Studio, Observatory, Control Center (interfaces web) | DOCUMENTED-ONLY | `docs/QUICKSTART.md`; `docs/OPERATOR-GUIDE.md`. Não iniciados |
| 21 | Execução de processos arbitrários isolados | DOCUMENTED-ONLY, indisponível no macOS | `runtime/README.md` ("Process isolation requirement": só Bubblewrap em Linux) |
| 22 | Cosmos Delta (`cosmos delta`, `report`) | DOCUMENTED-ONLY | `docs/QUICKSTART.md` §5 |
| 23 | Execução de SQL ou consulta analítica | UNPROVEN (ausência: `grep -rliE "postgres|duckdb|psycopg|sqlalchemy" runtime docs README.md tools pyproject.toml` só acha `docs/SYSTEM-BOUNDARY.md:246` (decisão adiada) e `docs/versions/COSMOS-2.0.md` (texto sobre substituição de tecnologia); `runtime/` só usa `sqlite3` para o próprio estado; `ExternalSystemAdapter` não tem driver) | Nenhum documento lido descreve consulta a bancos. `ExternalSystemAdapter` (`runtime/cosmos_runtime/effects.py:334`, lido; não executado) é um registro de handlers por `(action, resource_ref)` com `AuthorizedEffect`, sem driver de banco. O projeto usa `ToolAdapter` (`effects.py:302`) por exigir a ação `tool.invoke` (ver `../ARCHITECTURE.md` §5.3) |
| 24 | Contêiner Docker oficial / serviço de rede do Cosmos | UNPROVEN (ausência: `find . -iname 'Dockerfile*' -o -iname 'docker-compose*'` vazio) | Sem `Dockerfile` ou compose no repositório (busca vazia) |
| 25 | Daemon contínuo | DOCUMENTED-ONLY como PENDING | `docs/CAPABILITIES.md` §7 |

## 7. O que isso significa para o POC

1. O Cosmos é a camada de **memória semântica, política e proveniência** do agente. Ele não executa consultas, não tem catálogo de métricas e não calcula nada.
2. Duas integrações reais e comprovadas: (a) **grafo** (`.cosmos/graph.json`) com métricas, dimensões, regras e glossário, validado pelo esquema do Cosmos e lido pelo servidor MCP; (b) **governança de ferramentas** (`ToolAdapter` + `AuthorizationGateway`) com decisões e resultados persistidos no SQLite do Cosmos.
3. Os componentes adicionais necessários estão em `../ARCHITECTURE.md`: Query Engine em DuckDB, adaptador de ferramentas, cliente Gemini com function calling, pipelines, tabela de auditoria e isolamento de qualidade.
4. A busca por sinônimos em português não existe no MCP do Cosmos. A ferramenta `search_concepts` precisa de um adaptador que leia o mesmo `graph.json` e compare `aliases`.

## 8. Riscos e perguntas em aberto

- A API de runtime é de um produto em "Developer Preview"; pin por commit e testes de contrato (um teste do projeto roda o spike 5.9) detectam quebras.
- Formato do `ExternalLocator` em `resources` de capability: resolvido. A definição (`system` e `uri` obrigatórios; `external_id`, `revision`, `display` opcionais) foi lida em `spec/ontology/IDENTITY-AND-REFERENCES.md` e o nó com esse formato foi validado (5.10).
- `transition_episode` é API interna do runtime (5.9). Coberta por teste de contrato do projeto (`tests/integration/test_cosmos_contract.py`).
- `cosmos init` dentro de contêiner (sem `.git`) falha (5.3). O design usa um volume com World próprio (`../ARCHITECTURE.md` §11), **não verificado** por falta de Docker.
- O sync grava conhecimento já `active`. Se o projeto quiser o fluxo `candidate` → `validated` → `active`, isso exige estudar `runtime/candidate/admission_gate.py`. Fica fora do escopo do POC e declarado no README.
- O `frozen_core_intact: false` e o `doctor` em FAIL são esperados nesta instalação; não indicam defeito do projeto.

## 9. Apêndice: arquivos de apoio

Scripts e saídas no repositório (execute com `.venv/bin/python`):

| Arquivo | O que faz |
|---|---|
| `scripts/spikes/spike_tool_gateway.py` | Experimento 5.9 (`ToolAdapter` + `AuthorizationGateway`, permitir e negar). Saída: `docs/evidence/phase1/spike_tool_gateway.out` |
| `scripts/spikes/proto_sync.py <graph.json>` | Experimento 5.6 (grava `poc.metric`, regra, aresta e capability `metric.query` em um World descartável e valida). Saída: `docs/evidence/phase1/proto_sync.out`; `cosmos validate`: `docs/evidence/phase1/cosmos_validate.out` |
| `scripts/spikes/spike_capability_graph.py` | Experimento 5.10 (nó `capability` `tool.invoke` conduzindo o gateway). Saída: `docs/evidence/phase1/spike_capability_graph.out` |

A Fase 3 reimplementa esses scripts como `semantic/sync_to_cosmos.py`, `tests/integration/test_cosmos_sync.py` e `tests/integration/test_cosmos_contract.py`.
