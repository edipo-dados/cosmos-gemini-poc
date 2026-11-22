-- Permissões mínimas por papel (ver docs/ARCHITECTURE.md seção 8). Idempotente.
GRANT USAGE ON SCHEMA oltp, dq_lab TO poc_loader;
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA oltp, dq_lab TO poc_loader;
GRANT USAGE ON SCHEMA ops TO poc_loader, poc_reader, poc_dq, poc_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA ops TO poc_loader;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA ops TO poc_loader, poc_dq;

GRANT USAGE ON SCHEMA oltp TO poc_reader, poc_dq;
GRANT SELECT ON ALL TABLES IN SCHEMA oltp TO poc_reader, poc_dq;
GRANT SELECT ON ALL TABLES IN SCHEMA ops TO poc_reader, poc_dq, poc_app;

GRANT USAGE ON SCHEMA dq_lab TO poc_dq;
GRANT SELECT ON ALL TABLES IN SCHEMA dq_lab TO poc_dq;
GRANT INSERT ON ops.dq_run, ops.dq_result TO poc_dq;
GRANT UPDATE ON ops.dq_run TO poc_dq;

GRANT USAGE ON SCHEMA audit TO poc_app;
GRANT SELECT, INSERT ON audit.chat_turn, audit.query_audit TO poc_app;
GRANT UPDATE (answer, status, gemini_model, cosmos_episode_id) ON audit.chat_turn TO poc_app;
GRANT DELETE ON ops.generator_state TO poc_loader;
