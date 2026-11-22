from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_no_tools_or_runtime_at_repo_root():
    # `tools/` e `runtime/` pertencem ao pacote cosmos-platform
    assert not (ROOT / "tools").exists()
    assert not (ROOT / "runtime").exists()
