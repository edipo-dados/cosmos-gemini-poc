#!/usr/bin/env bash
# Serviço `init` do docker-compose: migrações, geração e carga, ETL, qualidade, World do Cosmos e sincronização semântica.
# Cada passo é idempotente (a carga não duplica registros; o World só é criado se faltar).
set -euo pipefail
cd /app
python -m database.migrate
python -m data.generators.run --seed "${SEED:-42}"
python -m pipelines.transform.run
python -m pipelines.quality.run
bash scripts/cosmos_world_init.sh
python -m semantic.sync_to_cosmos
cosmos validate "${COSMOS_WORLD_DIR:-/world}"
