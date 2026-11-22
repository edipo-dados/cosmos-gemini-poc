# Verificação de ambiente

| Item | Resultado |
|---|---|
| SO / shell | macOS 26.6, arm64, zsh |
| `python3` do sistema | 3.9.6 (insuficiente, requer 3.11+) |
| Outros Pythons (brew, pyenv, conda) | Nenhum. Homebrew não está instalado |
| Python 3.11 | Obtido via `uv` (instalado com `pip install --user uv`, uv 0.13.9). Criado `.venv` com CPython 3.11.18 |
| Docker | `docker` não encontrado. Daemon indisponível. `docker compose` indisponível |
| PostgreSQL local | `psql`, `pg_ctl` e `postgres` ausentes. Sem `brew services` |
| PostgreSQL via pip | Pacote `pgserver` instalado no `.venv`. Sobe um PostgreSQL 16.2 real (aarch64-apple-darwin) e responde `select version()` |
| git | 2.50.1 (Apple Git) |
| `GEMINI_API_KEY` | unset |
| Internet (PyPI) | Acessível |

## Estratégia de fallback

- **Docker indisponível:** `docker-compose.yml` e Dockerfiles serão escritos, mas não poderão ser verificados por execução neste ambiente. O relatório final deve declarar isso.
- **PostgreSQL:** executar um PostgreSQL 16 real (binários do `pgserver`, diretório de dados em `pgdata/`, escutando em TCP local) com o banco `analytics_poc` e papéis separados (admin/loader e leitura). Nenhum mock. Em Docker, a mesma configuração usa a imagem oficial `postgres`.
- **Chave Gemini ausente:** a integração será implementada e testada até a fronteira da API, sem mock apresentado como verificação. Chamadas ao vivo ficam como "não verificadas".
- **Python:** usar `/Users/edipo/projetos/poc-cosmos/.venv/bin/python` (3.11.18). O `uv` está em `~/Library/Python/3.9/bin`.
