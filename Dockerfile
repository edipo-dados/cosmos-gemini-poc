# Imagem única dos serviços Python (api, frontend, init). NÃO verificada por execução: Docker indisponível no ambiente de desenvolvimento.
FROM python:3.11-slim

ARG COSMOS_URL=https://github.com/cosmos-semantic/cosmos
ARG COSMOS_COMMIT=464175f6bfa641c30f0b2cdeb0ef84269fd202cb

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git bash \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# pgserver (PostgreSQL embutido) é só do desenvolvimento local sem Docker
COPY requirements.txt .
RUN grep -v '^pgserver' requirements.txt > /tmp/requirements.docker.txt \
    && pip install -r /tmp/requirements.docker.txt

# Cosmos no commit fixado, em modo editável (o mesmo caminho de scripts/bootstrap.sh)
RUN git clone "$COSMOS_URL" /opt/cosmos \
    && git -C /opt/cosmos checkout --quiet "$COSMOS_COMMIT" \
    && pip install -e /opt/cosmos

COPY app ./app
COPY agent ./agent
COPY data ./data
COPY database ./database
COPY pipelines ./pipelines
COPY semantic ./semantic
COPY scripts/cosmos_world_init.sh scripts/docker_init.sh ./scripts/
COPY tests/golden ./tests/golden
COPY .streamlit ./.streamlit

RUN useradd --create-home --uid 10001 poc \
    && mkdir -p /data /world \
    && chown -R poc:poc /data /world /app \
    && git config --system --add safe.directory /world
USER poc

ENV DUCKDB_PATH=/data/analytics.duckdb \
    DQ_LAB_DUCKDB_PATH=/data/dq_lab.duckdb \
    LOG_DIR=/data/logs \
    COSMOS_WORLD_DIR=/world

EXPOSE 8000 8501
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
