"""Validação ESTÁTICA do docker-compose.yml e do Dockerfile. Docker não está disponível: nada aqui executa contêineres,
`docker compose config` nem `docker build`. Os testes só leem os arquivos e cruzam serviços, variáveis, portas e volumes."""
from __future__ import annotations
import re
from pathlib import Path

import yaml

from app.config import Settings

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_TEXT = (ROOT / "docker-compose.yml").read_text()
COMPOSE = yaml.safe_load(COMPOSE_TEXT)
DOCKERFILE = (ROOT / "Dockerfile").read_text()
SERVICES = COMPOSE["services"]
ENV_EXAMPLE = dict(line.split("=", 1) for line in (ROOT / ".env.example").read_text().splitlines()
                   if line and not line.startswith("#") and "=" in line)
SETTINGS_FIELDS = {f.upper() for f in Settings.model_fields}
APP_SERVICES = ("init", "api", "frontend")


def env_of(name: str) -> dict:
    env = SERVICES[name].get("environment", {})
    return env if isinstance(env, dict) else dict(item.split("=", 1) for item in env)


def test_services_and_profiles():
    assert set(SERVICES) == {"postgres", "init", "api", "frontend"}
    assert SERVICES["init"]["profiles"] == ["init"]
    assert SERVICES["postgres"]["image"] == "postgres:16.2"
    assert "profiles" not in SERVICES["api"] and "profiles" not in SERVICES["frontend"]


def test_every_interpolated_variable_is_declared_in_env_example():
    names = set(re.findall(r"\$\{([A-Z_]+)[:?-]", COMPOSE_TEXT))
    assert names, "o compose deveria interpolar variáveis do .env"
    assert names <= set(ENV_EXAMPLE), names - set(ENV_EXAMPLE)


def test_env_example_has_no_real_secrets():
    assert ENV_EXAMPLE["GEMINI_API_KEY"] == ""
    for key, value in ENV_EXAMPLE.items():
        if key.endswith("_PASSWORD"):
            assert value.startswith("troque-me"), key


def test_container_env_names_are_settings_fields():
    for svc in APP_SERVICES:
        for name in env_of(svc):
            if name != "UI_USER_ID":
                assert name in SETTINGS_FIELDS, (svc, name)


def test_least_privilege_of_secrets_per_service():
    assert {k for k in env_of("api") if k.endswith("_PASSWORD")} == {"PG_APP_PASSWORD"}
    assert not [k for k in env_of("frontend") if k.endswith(("_PASSWORD", "_KEY"))]
    assert {k for k in env_of("init") if k.endswith("_PASSWORD")} == {f"PG_{r}_PASSWORD" for r in
                                                                       ("ADMIN", "LOADER", "READER", "DQ", "APP")}
    assert "GEMINI_API_KEY" not in env_of("init")


def test_network_wiring_and_ports():
    for svc in ("init", "api"):
        assert env_of(svc)["PG_HOST"] == "postgres" and env_of(svc)["PG_PORT"] == "5432"
    assert env_of("frontend")["API_URL"] == "http://api:8000"
    api_cmd, ui_cmd = " ".join(SERVICES["api"]["command"]), " ".join(SERVICES["frontend"]["command"])
    assert "--port 8000" in api_cmd and "--workers 1" in api_cmd
    assert "--server.port 8501" in ui_cmd and "app/frontend/Home.py" in ui_cmd
    assert SERVICES["api"]["ports"] == ["127.0.0.1:8000:8000"]
    assert SERVICES["frontend"]["ports"] == ["127.0.0.1:8501:8501"]
    assert "ports" not in SERVICES["postgres"]
    assert "/health" in " ".join(SERVICES["api"]["healthcheck"]["test"]) and "8000" in " ".join(SERVICES["api"]["healthcheck"]["test"])
    assert "/_stcore/health" in " ".join(SERVICES["frontend"]["healthcheck"]["test"])
    assert "pg_isready" in " ".join(SERVICES["postgres"]["healthcheck"]["test"])


def test_depends_on_references_and_health_conditions():
    for name, svc in SERVICES.items():
        for dep, cond in (svc.get("depends_on") or {}).items():
            assert dep in SERVICES, (name, dep)
            assert "healthcheck" in SERVICES[dep] and cond["condition"] == "service_healthy", (name, dep)
    assert "postgres" in SERVICES["init"]["depends_on"] and "api" in SERVICES["frontend"]["depends_on"]


def test_volumes_declared_and_paths_match_env():
    declared = set(COMPOSE["volumes"])
    assert declared == {"pg_data", "duckdb_data", "cosmos_world"}
    for name, svc in SERVICES.items():
        for vol in svc.get("volumes", []):
            src, dst = vol.split(":")[:2]
            if not src.startswith("."):
                assert src in declared, (name, vol)
            else:
                assert (ROOT / src).exists(), (name, vol)
    mounts = {s: {v.split(":")[1] for v in SERVICES[s].get("volumes", [])} for s in SERVICES}
    for svc in ("init", "api"):
        assert {"/data", "/world"} <= mounts[svc]
        assert env_of(svc)["COSMOS_WORLD_DIR"] == "/world" and env_of(svc)["DUCKDB_PATH"].startswith("/data/")
    assert "/docker-entrypoint-initdb.d:ro" in " ".join(SERVICES["postgres"]["volumes"])
    assert not mounts["frontend"]


def test_init_and_scripts_exist():
    assert SERVICES["init"]["command"] == ["bash", "scripts/docker_init.sh"]
    init = (ROOT / "scripts" / "docker_init.sh").read_text()
    for module in re.findall(r"python -m ([\w.]+)", init):
        assert (ROOT / (module.replace(".", "/") + ".py")).exists() or (ROOT / module.replace(".", "/") / "__main__.py").exists(), module
    for script in ("scripts/cosmos_world_init.sh", "scripts/docker_init.sh"):
        assert (ROOT / script).exists()
    assert list((ROOT / "database/postgres/init").glob("*.sql"))


def test_dockerfile_review():
    """Revisão ao estilo hadolint (regras equivalentes verificadas à mão: DL3006/DL3007/DL3008/DL3009/DL3013/DL3015/DL3042/DL3002)."""
    assert re.search(r"^FROM python:3\.11-slim\s*$", DOCKERFILE, re.M)
    assert ":latest" not in DOCKERFILE
    assert "--no-install-recommends" in DOCKERFILE and "rm -rf /var/lib/apt/lists/*" in DOCKERFILE
    assert "PIP_NO_CACHE_DIR=1" in DOCKERFILE
    assert re.search(r"^USER poc\s*$", DOCKERFILE, re.M)  # último USER não é root
    assert not re.search(r"^ENV\s.*(PASSWORD|API_KEY|SECRET)", DOCKERFILE, re.M | re.I)
    assert re.search(r"^EXPOSE 8000 8501\s*$", DOCKERFILE, re.M)
    for src in re.findall(r"^COPY (?!--)(\S+)", DOCKERFILE, re.M):
        assert (ROOT / src).exists(), src
    commit = re.search(r"COSMOS_COMMIT=(\w+)", DOCKERFILE).group(1)
    assert commit in (ROOT / "scripts" / "bootstrap.sh").read_text()
    assert "pgserver" in DOCKERFILE and "grep -v '^pgserver'" in DOCKERFILE


def test_dockerignore_keeps_secrets_and_state_out_of_image():
    ignored = (ROOT / ".dockerignore").read_text().splitlines()
    for item in (".env", "pgdata", ".cosmos", "cosmos.environment.json", ".git", ".venv", "*.duckdb"):
        assert item in ignored, item
