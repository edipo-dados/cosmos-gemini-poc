CREATE TABLE ops.generator_state (
    id          integer PRIMARY KEY CHECK (id = 1),
    seed        integer NOT NULL,
    params_hash text NOT NULL,
    loaded_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ops.etl_run (
    id                bigserial PRIMARY KEY,
    started_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz,
    status            text NOT NULL CHECK (status IN ('running','success','failed')),
    source_row_counts jsonb,
    duckdb_path       text,
    duration_ms       integer,
    error             text
);

CREATE TABLE ops.dq_run (
    id          bigserial PRIMARY KEY,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    target      text NOT NULL CHECK (target IN ('oltp','dq_lab')),
    trigger     text NOT NULL,
    etl_run_id  bigint,
    status      text NOT NULL CHECK (status IN ('running','passed','failed')),
    summary     jsonb
);

CREATE TABLE ops.dq_result (
    id         bigserial PRIMARY KEY,
    dq_run_id  bigint NOT NULL REFERENCES ops.dq_run (id),
    kind       text NOT NULL CHECK (kind IN ('rule','reconciliation')),
    name       text NOT NULL,
    violations integer,
    expected   text,
    actual     text,
    passed     boolean NOT NULL,
    detail     jsonb
);
CREATE INDEX ix_dq_result_run ON ops.dq_result (dq_run_id);
