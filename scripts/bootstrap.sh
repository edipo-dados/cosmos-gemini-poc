#!/usr/bin/env bash
# Instalação das dependências e do Cosmos (Fases 2 e 3). Reexecutar é seguro: cada passo só age se faltar algo.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/Library/Python/3.9/bin:$PATH"
COSMOS_URL="https://github.com/cosmos-semantic/cosmos"
COSMOS_COMMIT="464175f6bfa641c30f0b2cdeb0ef84269fd202cb"

[ -d .venv ] || uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt
[ -f .env ] || { cp .env.example .env; echo "Criado .env a partir de .env.example: troque as senhas."; }

# Cosmos no commit fixado (produto em Developer Preview: o pin evita quebra silenciosa)
if [ ! -d .vendor/cosmos/.git ]; then
  mkdir -p .vendor
  git clone "$COSMOS_URL" .vendor/cosmos
fi
git -C .vendor/cosmos checkout --quiet "$COSMOS_COMMIT"
if ! .venv/bin/python -c "import tools.validate_ontology, runtime.cosmos_runtime" 2>/dev/null; then
  uv pip install --python .venv/bin/python -e .vendor/cosmos
fi

# World do projeto (exige repositório git com ao menos um commit)
if [ ! -f cosmos.environment.json ]; then
  .venv/bin/cosmos init .
fi
# Os hooks gerados apontam para um caminho fixo de Windows e não funcionam aqui: não são usados nem versionados.
rm -rf .githooks
echo "Bootstrap concluído. Próximo passo: make sync (catálogo semântico -> Cosmos)."
