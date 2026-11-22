-- Papéis (sem senha: o runner define por ALTER ROLE a partir do ambiente) e schemas.
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['poc_loader','poc_reader','poc_dq','poc_app'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I LOGIN', r);
    END IF;
  END LOOP;
END $$;

ALTER ROLE poc_reader SET default_transaction_read_only = on;

CREATE SCHEMA IF NOT EXISTS oltp;
CREATE SCHEMA IF NOT EXISTS dq_lab;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS ops;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
DO $$
BEGIN
  EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO poc_loader, poc_reader, poc_dq, poc_app', current_database());
END $$;
