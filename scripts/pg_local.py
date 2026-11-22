"""PostgreSQL 16 real e local (binários do pacote pgserver), sem Docker.

Uso: python scripts/pg_local.py start|stop|status [--datadir pgdata] [--port 54329]
Escuta em TCP 127.0.0.1. O superusuário inicial é poc_admin, com PG_ADMIN_PASSWORD.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pgserver._commands import POSTGRES_BIN_PATH  # noqa: E402

from app.config import get_settings  # noqa: E402


def _bin(name: str) -> str:
    return str(Path(POSTGRES_BIN_PATH) / name)


def _socket_dir(port: int) -> Path:
    d = Path(tempfile.gettempdir()) / f"poc_pg_{port}"
    d.mkdir(exist_ok=True)
    return d


def init_cluster(datadir: Path, admin_password: str) -> None:
    if (datadir / "PG_VERSION").exists():
        return
    datadir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False) as pw:
        pw.write(admin_password)
    os.chmod(pw.name, 0o600)
    try:
        subprocess.run(
            [_bin("initdb"), "-D", str(datadir), "-U", "poc_admin", "--pwfile", pw.name,
             "--auth=scram-sha-256", "-E", "UTF8", "--locale=C"],
            check=True, capture_output=True, text=True,
        )
    finally:
        os.unlink(pw.name)


def is_running(datadir: Path) -> bool:
    r = subprocess.run([_bin("pg_ctl"), "-D", str(datadir), "status"], capture_output=True, text=True)
    return r.returncode == 0


def start(datadir: Path, port: int, admin_password: str) -> None:
    init_cluster(datadir, admin_password)
    if is_running(datadir):
        return
    sock = _socket_dir(port)
    subprocess.run(
        [_bin("pg_ctl"), "-D", str(datadir), "-l", str(datadir / "pg.log"), "-w",
         "-o", f"-p {port} -h 127.0.0.1 -k {sock}", "start"],
        check=True, capture_output=True, text=True,
    )


def stop(datadir: Path) -> None:
    if (datadir / "PG_VERSION").exists() and is_running(datadir):
        subprocess.run([_bin("pg_ctl"), "-D", str(datadir), "-m", "fast", "-w", "stop"],
                       check=True, capture_output=True, text=True)


def main() -> int:
    s = get_settings()
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["start", "stop", "status"])
    ap.add_argument("--datadir", default=str(ROOT / "pgdata"))
    ap.add_argument("--port", type=int, default=s.pg_port)
    a = ap.parse_args()
    datadir = Path(a.datadir)
    if a.action == "start":
        start(datadir, a.port, s.password("admin"))
        print(f"PostgreSQL em execução em 127.0.0.1:{a.port} (datadir={datadir})")
    elif a.action == "stop":
        stop(datadir)
        print("PostgreSQL parado")
    else:
        print("em execução" if (datadir / "PG_VERSION").exists() and is_running(datadir) else "parado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
