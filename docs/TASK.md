# Projeto: Cosmos Semantic + Gemini — POC de Inteligência Analítica

## 1. Objetivo
Desenvolver uma POC funcional de uma plataforma de Analytics Conversacional, utilizando Google Gemini API como LLM e Cosmos Semantic como ambiente de contexto, semântica e governança para agentes. A aplicação deverá permitir que usuários façam perguntas sobre dados corporativos em linguagem natural, recebam respostas fundamentadas em dados reais armazenados em bancos de dados e consigam visualizar as métricas, regras de negócio, SQL executado e evidências que sustentam cada resposta. Não desenvolver apenas um chatbot demonstrativo. Construir uma plataforma funcional, com bancos de dados populados, pipelines de dados, camada semântica, integração com LLM e interface web.

## 2. Primeira atividade obrigatória: entender o Cosmos
Antes de implementar qualquer código:
1. Consulte o repositório oficial: https://github.com/cosmos-semantic/cosmos (clone it locally into a git-ignored folder /Users/edipo/projetos/poc-cosmos/.vendor/cosmos; use web fetch/search if clone fails).
2. Leia obrigatoriamente: AGENTS.md, README.md, docs/ROADMAP.md, docs/OPERATOR-GUIDE.md, runtime/README.md, documentação da versão e dos recursos que serão utilizados.
3. Identifique: arquitetura do Cosmos; conceito de World; como persistir contexto e conhecimento semântico; como registrar capacidades e ferramentas; como integrar modelos externos; como conectar agentes e ferramentas; quais recursos estão disponíveis na versão atual.
4. Não invente comandos, APIs, ferramentas MCP ou funcionalidades que não estejam documentados.
5. Não confunda o Cosmos com uma Semantic Layer SQL tradicional. Identifique como ele pode atuar na arquitetura proposta e quais componentes adicionais serão necessários para consultar os bancos.
6. Antes de implementar, documente a arquitetura de integração entre Cosmos, Gemini e os bancos (docs/ARCHITECTURE.md with decisions and a table of proven vs. unproven Cosmos capabilities, with citations to the Cosmos files read).
O Cosmos deverá ser utilizado de verdade, e não apenas citado na documentação do projeto.

## 3. Stack
Python 3.11+, Google Gemini API (AI Studio) com SDK oficial google-genai, Cosmos Semantic, PostgreSQL, DuckDB, FastAPI, Streamlit, Docker e Docker Compose, SQLAlchemy, Pandas ou Polars, Pytest. Versões estáveis e compatíveis (pin them). GEMINI_API_KEY por variável de ambiente; modelo configurável por GEMINI_MODEL. Não usar Bedrock, OpenAI ou outros LLMs.

## 4. Arquitetura funcional
A. LLM Layer: Gemini interpreta perguntas, identifica intenção, métricas e dimensões, solicita ferramentas, interpreta resultados e responde em português. Usar Function Calling ou MCP conforme compatibilidade comprovada. Gemini NÃO executa SQL arbitrário nos bancos.
B. Cosmos Semantic Layer: usar o Cosmos para persistir/organizar contexto semântico e capacidades: contexto persistente, definições semânticas, glossário, regras e políticas, documentação de capacidades, proveniência e rastreabilidade (investigar mecanismos nativos). Se o Cosmos não executa consultas analíticas, implementar adaptador de ferramentas entre agente e motor de consultas. Não atribuir ao Cosmos funcionalidades não comprovadas.
C. Query Engine: serviço que recebe solicitações de métricas, valida métricas e dimensões permitidas, aplica regras de negócio, constrói SQL controlado, executa em DuckDB, retorna dados e evidências. O agente consulta métricas cadastradas, não cria queries livres.
D. Data Engineering: pipelines para gerar dados sintéticos, carregar PostgreSQL, extrair/transformar, alimentar DuckDB, validar qualidade, reconciliar resultados entre bancos.

## 5. Bancos e massa de dados (dados reais nos bancos, sem mocks/DataFrames só em memória)
PostgreSQL OLTP: banco analytics_poc com tabelas customers, products, categories, regions, orders, order_items, payments, refunds; PKs, FKs, índices, constraints.
Dados sintéticos com Faker pt_BR. Volume: 5.000 clientes, 500 produtos, 20 categorias, 5 regiões, 20.000 pedidos, 35.000+ itens, 20.000 pagamentos, reembolsos variável. Histórico de 24 meses. Clientes de diferentes regiões/perfis/segmentos; produtos de várias categorias; pedidos em várias datas; várias formas de pagamento; pedidos pagos, pendentes, cancelados e reembolsados; valores e padrões de compra variados. Determinístico com seed configurável. Recarga idempotente (sem duplicar). Sem dados pessoais reais.
DuckDB analítico persistente: tabelas/views dim_customer, dim_product, dim_region, dim_date, fact_orders, fact_order_items, fact_payments, fact_refunds. Carga/transformação a partir do PostgreSQL, reproduzível, com logs.

## 6. Semantic Model e regras
Catálogo semântico governado. Cada métrica: nome técnico, nome de negócio, descrição, fórmula, fonte de dados, dimensões permitidas, filtros aplicáveis, responsável, versão, testes de validação. Métricas iniciais:
1. gross_revenue: valor bruto dos pedidos pagos, antes dos reembolsos.
2. net_revenue: valor dos pedidos pagos menos reembolsos efetivados.
3. order_count: quantidade de pedidos.
4. average_order_value: receita líquida / quantidade de pedidos pagos.
5. active_customers: clientes com pelo menos um pedido pago nos últimos 90 dias.
6. cancellation_rate: pedidos cancelados / total de pedidos.
7. refund_amount: valor total dos reembolsos efetivados.
8. monthly_revenue_growth: crescimento % da receita líquida vs. mês anterior.
Documentar explicitamente denominadores, filtros, tratamento de status e regras para evitar ambiguidades.
Dimensões: Data, Mês, Ano, Região, Segmento de cliente, Categoria, Produto, Forma de pagamento, Status do pedido.
Glossário de negócio com sinônimos em português (Faturamento = Receita; Ticket médio = Average Order Value; Cliente ativo = Active Customer; Cancelamento = Cancellation; etc.).
O Cosmos deve receber e persistir contexto e definições semânticas por seus mecanismos documentados. Se precisar de catálogo complementar, manter artefatos versionados no projeto (semantic/ YAML) e estabelecer claramente a relação com o Cosmos (e.g. YAML is source of truth, a sync script loads into Cosmos, with a test that verifies the content in Cosmos).

## 7. Qualidade e governança
Testes que detectem: pedidos sem clientes; itens sem produtos; pagamentos duplicados; cancelados com pagamentos; reembolsos > valor pago; valores negativos indevidos; datas inconsistentes; divergência de métricas Postgres vs DuckDB. Incluir inconsistências controladas nos dados sintéticos para demonstrar detecção, SEPARANDO dados de teste com inconsistências dos dados válidos usados nos cálculos oficiais (e.g. separate schema/dataset/fixtures, never contaminating official metrics).
Trilha de auditoria: pergunta original, usuário, métrica consultada, filtros, SQL executado, data/hora, fonte, resultado, evidências (persist in a DB table).

## 8. Ferramentas do agente
search_concepts, explain_metric, list_metrics, query_metric, list_dimensions, show_sql, get_evidence. Verificar primeiro se há equivalentes nativos no Cosmos; senão implementar via camada adaptadora. Execução somente leitura. Validar argumentos, métricas, dimensões, filtros e limites no backend.

## 9. Interface Streamlit (identidade visual profissional)
Pág 1 Analytics Assistant: chat com Gemini; perguntas exemplo: faturamento últimos 30 dias; região com maior receita; categoria com maior ticket médio; quantos clientes ativos; comparar faturamento dos últimos dois meses; taxa de cancelamento; explicar como o faturamento líquido é calculado. Mostrar resposta, indicadores numéricos, gráficos, métricas usadas, dimensões e filtros, fonte, evidências.
Pág 2 Semantic Catalog: métricas, descrições, fórmulas, dimensões, regras, glossário, responsáveis.
Pág 3 Data Quality: volume de registros, qualidade, inconsistências, histórico de validações, status das cargas.
Pág 4 SQL & Evidence: SQL executado, fonte, métrica, filtros, resultado, evidências e rastreabilidade.
Pág 5 Data Overview: receita bruta, líquida, ticket médio, clientes ativos, pedidos, taxa de cancelamento, receita por mês/região/categoria.

## 10. Segurança
Segredos só por env; .env no .gitignore; credenciais de banco separadas; usuário PostgreSQL com permissões mínimas; conexão read-only para consultas analíticas; validação de inputs; proteção contra SQL injection; limite de linhas; timeout de queries; logs sem API keys.

## 11. Estrutura sugerida (ajustar se o Cosmos exigir)
app/{frontend,api,services}, cosmos/{worlds,documentation}, data/{generators,seeds,samples}, database/{postgres,duckdb,migrations}, pipelines/{extract,transform,quality}, semantic/{metrics,dimensions,rules,glossary}, agent/{gemini,tools,orchestration}, tests/, docker-compose.yml, requirements.txt, .env.example, README.md

## 12. Docker Compose
PostgreSQL, API FastAPI, frontend Streamlit, serviços necessários ao Cosmos (conforme documentação), volumes persistentes; DuckDB em arquivo persistente em volume; health checks; iniciar com comandos simples documentados.

## 13. Critérios de aceite
1 Postgres funcionando e populado. 2 DuckDB funcionando e populado. 3 Pipeline de carga executando. 4 Cosmos inicializado e integrado conforme recursos comprovados. 5 Gemini conectado com API Key configurada. 6 Agente descobre conceitos e consulta métricas. 7 Respostas numéricas iguais às queries SQL de referência. 8 SQL inspecionável. 9 Evidências disponíveis. 10 Interface web funcional. 11 Testes automatizados passando. 12 Aplicação inicia seguindo o README.
Criar pelo menos 15 perguntas de teste com resultados esperados pré-calculados (via SQL de referência independente). Incluir testes para perguntas ambíguas, métricas inexistentes e tentativas de acesso a dimensões não autorizadas.

## 14. Estratégia: fases, validando cada uma
Fase 1 Discovery (inspecionar Cosmos, validar recursos, arquitetura, decisões). Fase 2 Data Foundation (Docker, Postgres, modelo, geração, DuckDB, ETL). Fase 3 Semantic Governance (métricas, dimensões, regras, glossário, integração Cosmos). Fase 4 Gemini Integration (cliente, function calling, ferramentas, orquestração, consulta semântica). Fase 5 Frontend. Fase 6 Validation (testes, reconciliação, segurança, performance, documentação). Ao concluir cada fase, executar testes e documentar o resultado (docs/PHASE_REPORTS.md). Uma fase não está concluída só porque arquivos foram criados.

## 15. Instrução final
Atuar como arquiteto de software e engenheiro de dados sênior. Simples, funcional, modular, reproduzível. Sem mocks para integrações do escopo de aceite. Não inventar recursos do Cosmos. Não deixar componentes críticos apenas simulados. Se uma integração não for possível, documentar limitação, apresentar alternativas e implementar o adaptador necessário. Ao final, README em pt-BR com instruções completas de execução local, carga dos dados, configuração do Gemini e roteiro de demonstração. O relatório final deve declarar honestamente quais critérios de aceite foram verificados por execução (com evidência: comandos e saídas) e quais não (e.g. chamadas Gemini ao vivo sem chave, Docker se indisponível).

Extra context from the orchestrator: machine is macOS/zsh. Never commit secrets. If GEMINI_API_KEY is absent, the Gemini integration must be fully implemented and tested up to the API boundary and clearly reported as not live-verified (never mock it as if verified). Final docs in pt-BR; code identifiers in English.
