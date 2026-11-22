# Uso do Cosmos neste projeto (Fase 3)

Este documento descreve o que o projeto grava no Cosmos, como isso se relaciona com o catálogo YAML e o que foi ou não comprovado por execução. Versão do Cosmos: commit `464175f6bfa641c30f0b2cdeb0ef84269fd202cb` (`v1.6.0-preview`). Detalhes da descoberta em `docs/history/COSMOS_DISCOVERY.md`.

## Relação entre o catálogo YAML e o Cosmos

| Item | Papel |
|---|---|
| `semantic/` (YAML, versionado em git) | **Fonte de verdade.** Métricas, dimensões, regras, glossário, ferramentas permitidas. Lido pelo Query Engine para montar SQL. |
| `.cosmos/graph.json` (World do Cosmos) | **Projeção** do catálogo: o agente lê significado, regras e política aqui. Não é fonte de números nem de SQL. |
| `semantic/sync_to_cosmos.py` | Leva o YAML ao grafo. Valida com `validate_graph` do Cosmos antes de gravar e grava de forma atômica. |

Regras do sync:

- Todo registro gerado leva `extensions["poc.sync"] = {owner: "semantic-sync", catalog_version, source_uri}`. A cada execução esses registros são removidos e regravados a partir do YAML. O que sai do YAML sai do grafo. Os registros criados por `cosmos init` (sem o marcador) ficam intactos.
- IDs vêm de `stable_cosmos_ref("<chave semântica>")`: reexecutar não duplica e não muda o arquivo (a segunda execução não grava nada).
- `created_at` é preservado entre execuções. `updated_at` só aparece quando o conteúdo do registro mudou.
- Proveniência de cada registro: `created_by` (ator criado pelo `cosmos init`) e `imported_from` com localizador externo `{system: "poc-semantic-catalog", uri: "semantic/metrics/<nome>.yaml", revision: <catalog_version>}`. `authority.class` é `external` com o mesmo localizador: o Cosmos não é dono da definição.
- Sem World (`cosmos.environment.json` ou `.cosmos/graph.json` ausentes), o sync sai com código 2 e `world_not_initialized`. Ele nunca cria o World.
- O Query Engine **não** lê o grafo. Um erro de sync não muda números. Um teste confere que a versão de cada métrica no grafo é igual à do YAML.

## O que vira registro no Cosmos

| Origem no YAML | Registro no grafo |
|---|---|
| Métrica | nó `entity`, `entity_type: poc.metric`; `display_name` = nome técnico; `aliases` = nome de negócio; `extensions["poc.metric"]` = fórmula, fonte, denominador, tratamento de status, base de tempo, filtro base, dimensões permitidas, filtros aplicáveis, responsável, versão, testes |
| Dimensão | nó `entity`, `entity_type: poc.dimension`, com a lista de métricas que a aceitam |
| Termo do glossário | nó `entity`, `entity_type: poc.glossary_term`; `aliases` = sinônimos em português; `maps_to` aponta para os IDs de métricas ou dimensões |
| Regra de negócio | nó `knowledge`, `knowledge_class: rule`, `lifecycle_state: active`; aresta `core.governed_by` de cada métrica afetada para a regra |
| Ferramenta do agente | nó `capability`, `action: tool.invoke`, `decision: allow`, `resources: [{system: "poc-tools", uri: "tool:<nome>"}]`, `grantee_refs` = ator `poc.agent` |
| Agente e usuário | nós `actor`: `poc.agent` (service) e `poc.user` (human) |

## Comprovado por execução nesta fase

Cada linha tem teste automatizado em `tests/integration/test_cosmos_sync.py` ou comando em `docs/history/PHASE_REPORTS.md` (Fase 3).

| Afirmação | Rótulo |
|---|---|
| Gravar `entity`, `knowledge` (rule), `capability`, `actor` e arestas `core.governed_by` em `.cosmos/graph.json` passa em `validate_graph` e em `cosmos validate` (`valid: true`) | PROVEN |
| O servidor MCP somente leitura do Cosmos, em subprocesso com `COSMOS_GRAPH` e `cwd` fixos, devolve as 8 métricas, 9 dimensões, o glossário e as regras do sync com os mesmos textos e versões do YAML (`cosmos_query` por `id`) | PROVEN |
| `cosmos_explain` de cada métrica lista as regras por `core.governed_by`, e o texto de cada regra é igual ao do YAML | PROVEN |
| `cosmos_tool` lista os 7 nós `capability` do sync | PROVEN |
| `ToolAdapter` + `AuthorizationGateway` reais: com um provider escrito pelo projeto que lê os nós `capability` do grafo, a ferramenta declarada é permitida, uma não declarada é negada, e remover a ferramenta do YAML e sincronizar passa a negá-la | PROVEN (o provider é código do projeto) |
| Mudança no YAML (versão, responsável, regra removida, sinônimo removido) muda o grafo; nada fica órfão | PROVEN |

## Não comprovado ou fora do escopo

| Item | Rótulo |
|---|---|
| O gateway carregar sozinho os nós `capability` do `graph.json` | UNPROVEN. O código do gateway só aceita o `dict` de um provider. O mapeamento nó → estado é do projeto. |
| Fluxo oficial de admissão de conhecimento (Candidate Intake) | DOCUMENTED-ONLY. O sync grava conhecimento já `active`, sem passar pela admissão. Limitação declarada. |
| Busca por sinônimo pelo MCP do Cosmos | UNPROVEN. `cosmos_query` não filtra `aliases`. A busca por sinônimos em português será feita por adaptador do projeto sobre o mesmo grafo (Fase 4). |
| Cosmos executar consultas analíticas ou SQL | Não existe. O Query Engine do projeto calcula tudo. |
| Suporte oficial ao servidor MCP | UNPROVEN (o repositório do Cosmos marca como pendente). A execução foi provada, o suporte não. |
| Arestas `core.references` e `core.supports` | DOCUMENTED-ONLY. Não usadas. |

## Comandos

```bash
make sync                                   # sync do YAML para o World e cosmos validate
.venv/bin/python -m semantic.sync_to_cosmos # só o sync (imprime o resumo em JSON)
.venv/bin/cosmos validate .                 # validação do próprio Cosmos
```
