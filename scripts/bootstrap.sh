#!/usr/bin/env bash
# Instalação das dependências (Fase 2). A parte do Cosmos entra na Fase 3.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/Library/Python/3.9/bin:$PATH"
[ -d .venv ] || uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r requirements.txt
[ -f .env ] || { cp .env.example .env; echo "Criado .env a partir de .env.example: troque as senhas."; }
