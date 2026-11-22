CREATE TABLE audit.chat_turn (
    turn_id           uuid PRIMARY KEY,
    created_at        timestamptz NOT NULL DEFAULT now(),
    user_id           text NOT NULL,
    session_id        text NOT NULL,
    question          text NOT NULL CHECK (char_length(question) BETWEEN 1 AND 2000),
    answer            text,
    status            text NOT NULL CHECK (status IN ('started','ok','incomplete','blocked','error')),
    gemini_model      text,
    cosmos_episode_id text,
    request_id        text NOT NULL
);

CREATE TABLE audit.query_audit (
    query_id            uuid PRIMARY KEY,
    turn_id             uuid REFERENCES audit.chat_turn (turn_id),
    created_at          timestamptz NOT NULL DEFAULT now(),
    user_id             text NOT NULL,
    tool_name           text NOT NULL,
    metric              text,
    dimensions          jsonb,
    filters             jsonb,
    row_limit           integer,
    sql_text            text,
    sql_params          jsonb,
    source              text,
    etl_run_id          bigint,
    catalog_version     text,
    status              text NOT NULL CHECK (status IN ('ok','rejected','error')),
    error_code          text,
    row_count           integer,
    duration_ms         integer,
    result              jsonb,
    evidence            jsonb,
    cosmos_episode_id   text,
    cosmos_decision_id  text
);
CREATE INDEX ix_query_audit_user ON audit.query_audit (user_id, created_at);
CREATE INDEX ix_query_audit_turn ON audit.query_audit (turn_id);

CREATE FUNCTION audit.chat_turn_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'audit.chat_turn: DELETE não permitido';
  END IF;
  IF OLD.status <> 'started' OR NEW.status = 'started' THEN
    RAISE EXCEPTION 'audit.chat_turn: só a transição started -> status final é permitida';
  END IF;
  IF NEW.turn_id IS DISTINCT FROM OLD.turn_id OR NEW.question IS DISTINCT FROM OLD.question
     OR NEW.user_id IS DISTINCT FROM OLD.user_id OR NEW.session_id IS DISTINCT FROM OLD.session_id
     OR NEW.created_at IS DISTINCT FROM OLD.created_at OR NEW.request_id IS DISTINCT FROM OLD.request_id THEN
    RAISE EXCEPTION 'audit.chat_turn: colunas imutáveis não podem mudar';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER trg_chat_turn_guard BEFORE UPDATE OR DELETE ON audit.chat_turn
  FOR EACH ROW EXECUTE FUNCTION audit.chat_turn_guard();

CREATE FUNCTION audit.append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% em %.% não permitido: tabela somente de inserção', TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME;
END $$;
CREATE TRIGGER trg_query_audit_append_only BEFORE UPDATE OR DELETE ON audit.query_audit
  FOR EACH ROW EXECUTE FUNCTION audit.append_only();
