"""Executa as regras de qualidade (rules/*.sql) em um schema e registra em ops.dq_*."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import Engine, text

RULES_DIR = Path(__file__).resolve().parent / "rules"
SCHEMAS = ("oltp", "dq_lab")


@dataclass
class RuleResult:
    name: str
    violations: int
    sample: list[dict] = field(default_factory=list)


def rule_names() -> list[str]:
    return sorted(p.stem for p in RULES_DIR.glob("*.sql"))


def rule_sql(name: str, schema: str) -> str:
    if schema not in SCHEMAS:
        raise ValueError(f"schema não permitido: {schema}")
    return (RULES_DIR / f"{name}.sql").read_text(encoding="utf-8").format(schema=schema).strip()


def run_rules(engine: Engine, schema: str, data_end_date: date) -> list[RuleResult]:
    results = []
    with engine.connect() as conn:
        for name in rule_names():
            sql = rule_sql(name, schema)
            params = {"data_end_date": data_end_date.isoformat()}
            n = conn.execute(text(f"SELECT count(*) FROM ({sql}) v"), params).scalar_one()
            sample = [dict(r._mapping) for r in conn.execute(text(f"SELECT * FROM ({sql}) v LIMIT 5"), params)]
            results.append(RuleResult(name, int(n), sample))
    return results


def start_run(engine: Engine, target: str, trigger: str, etl_run_id: int | None = None) -> int:
    with engine.begin() as c:
        return c.execute(text(
            "INSERT INTO ops.dq_run (target, trigger, etl_run_id, status) VALUES (:t, :g, :e, 'running') RETURNING id"),
            {"t": target, "g": trigger, "e": etl_run_id}).scalar_one()


def record_result(engine: Engine, run_id: int, kind: str, name: str, passed: bool, *, violations: int | None = None,
                  expected: str | None = None, actual: str | None = None, detail: object = None) -> None:
    with engine.begin() as c:
        c.execute(text(
            "INSERT INTO ops.dq_result (dq_run_id, kind, name, violations, expected, actual, passed, detail) "
            "VALUES (:r, :k, :n, :v, :e, :a, :p, CAST(:d AS jsonb))"),
            {"r": run_id, "k": kind, "n": name, "v": violations, "e": expected, "a": actual, "p": passed,
             "d": json.dumps(detail, default=str) if detail is not None else None})


def finish_run(engine: Engine, run_id: int, passed: bool, summary: dict) -> None:
    with engine.begin() as c:
        c.execute(text("UPDATE ops.dq_run SET finished_at = now(), status = :s, summary = CAST(:j AS jsonb) WHERE id = :i"),
                  {"s": "passed" if passed else "failed", "j": json.dumps(summary, default=str), "i": run_id})
