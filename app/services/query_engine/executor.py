"""Execução em DuckDB: conexão somente leitura por requisição, timeout com interrupt(), corte de linhas."""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb

from semantic.loader import Catalog

from .errors import QueryEngineError
from .sql_builder import assert_single_select

DEFAULT_TIMEOUT_S = 10.0
HARD_ROW_LIMIT = 1000

# cache de valores categóricos por (arquivo, etl_run_id): um novo ETL invalida sozinho
_DOMAIN_CACHE: dict[tuple[str, int], dict[str, set[str]]] = {}
_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True)
class DataContext:
    etl_run_id: int
    data_range: tuple[date, date]
    domain: dict[str, set[str]]


@dataclass(frozen=True)
class ExecResult:
    columns: list[str]
    rows: list[tuple]
    truncated_at_hard_limit: bool
    duration_ms: int


class DuckDBExecutor:
    def __init__(self, path: Path | str, timeout_s: float = DEFAULT_TIMEOUT_S):
        self.path = str(path)
        self.timeout_s = timeout_s

    @contextmanager
    def connection(self):
        if not Path(self.path).is_file():
            raise QueryEngineError("internal_error", "Arquivo DuckDB analítico não encontrado. Rode o ETL.")
        con = duckdb.connect(self.path, read_only=True)
        try:
            yield con
        finally:
            con.close()

    def context(self, con: duckdb.DuckDBPyConnection, catalog: Catalog) -> DataContext:
        """Lê etl_meta, o intervalo de datas e os valores categóricos (com cache por etl_run_id)."""
        etl_run_id = int(con.execute("SELECT etl_run_id FROM etl_meta").fetchone()[0])
        lo, hi = con.execute("SELECT MIN(date_key), MAX(date_key) FROM dim_date").fetchone()
        key = (self.path, etl_run_id)
        with _CACHE_LOCK:
            domain = _DOMAIN_CACHE.get(key)
        if domain is None:
            domain = {}
            for d in catalog.dimensions.values():
                if d["type"] == "categorical":
                    dom = d["domain"]  # identificadores vêm do YAML
                    rows = con.execute(f'SELECT DISTINCT {dom["column"]} FROM {dom["table"]} WHERE {dom["column"]} IS NOT NULL').fetchall()
                    domain[d["name"]] = {r[0] for r in rows}
            with _CACHE_LOCK:
                for stale in [k for k in _DOMAIN_CACHE if k[0] == self.path]:
                    del _DOMAIN_CACHE[stale]
                _DOMAIN_CACHE[key] = domain
        return DataContext(etl_run_id, (lo, hi), domain)

    def execute(self, con: duckdb.DuckDBPyConnection, sql: str, params: list, timeout_s: float | None = None) -> ExecResult:
        assert_single_select(sql)
        timeout = self.timeout_s if timeout_s is None else timeout_s
        fired = threading.Event()

        def _interrupt():
            fired.set()
            con.interrupt()

        timer = threading.Timer(timeout, _interrupt)
        start = time.perf_counter()
        timer.start()
        try:
            cur = con.execute(sql, params)
            rows = cur.fetchmany(HARD_ROW_LIMIT + 1)
            columns = [c[0] for c in cur.description]
        except duckdb.InterruptException as exc:
            raise QueryEngineError("query_timeout", f"A consulta excedeu {timeout:g} s e foi interrompida.") from exc
        except duckdb.Error as exc:
            if fired.is_set():
                raise QueryEngineError("query_timeout", f"A consulta excedeu {timeout:g} s e foi interrompida.") from exc
            raise QueryEngineError("internal_error", f"Falha ao executar a consulta: {type(exc).__name__}") from exc
        finally:
            timer.cancel()
        over = len(rows) > HARD_ROW_LIMIT
        return ExecResult(columns, rows[:HARD_ROW_LIMIT], over, int((time.perf_counter() - start) * 1000))
