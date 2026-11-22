"""World descartável do Cosmos (git init + commit + `cosmos init`) com o catálogo sincronizado."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from semantic.loader import load_catalog
from semantic.sync_to_cosmos import sync

COSMOS_BIN = Path(sys.executable).parent / "cosmos"


def make_synced_world(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "README.md").write_text("# mundo de teste\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", "commit", "-qm", "init"], cwd=path, check=True)
    subprocess.run([str(COSMOS_BIN), "init", str(path)], check=True, capture_output=True)
    summary = sync(path, load_catalog())
    assert summary["validate_graph_errors"] == [] and summary["written"] is True
    return path
