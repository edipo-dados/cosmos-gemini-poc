#!/usr/bin/env bash
# Cria o World do Cosmos em COSMOS_WORLD_DIR (padrão /world) se ainda não existir. Reexecutar é seguro.
# `cosmos init` exige um repositório git com ao menos um commit (docs/ARCHITECTURE.md, seção 11).
set -euo pipefail
WORLD="${COSMOS_WORLD_DIR:-/world}"
mkdir -p "$WORLD"
if [ -f "$WORLD/cosmos.environment.json" ] && [ -f "$WORLD/.cosmos/graph.json" ]; then
  echo "World já inicializado em $WORLD"
  exit 0
fi
cd "$WORLD"
if ! git rev-parse HEAD >/dev/null 2>&1; then
  git init -q
  printf '# World do Cosmos Analytics POC\n' > README.md
  git add README.md
  git -c user.name="poc-init" -c user.email="poc-init@example.invalid" commit -qm "chore: world inicial"
fi
cosmos init "$WORLD"
rm -rf "$WORLD/.githooks"  # os hooks gerados não são usados neste projeto
echo "World inicializado em $WORLD"
