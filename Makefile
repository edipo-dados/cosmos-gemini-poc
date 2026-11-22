PY ?= .venv/bin/python
# Carrega .env (se existir) para os alvos
ifneq (,$(wildcard .env))
include .env
export
endif

.PHONY: pg-start pg-stop migrate load etl quality test data

pg-start:
	$(PY) scripts/pg_local.py start
pg-stop:
	$(PY) scripts/pg_local.py stop
migrate:
	$(PY) -m database.migrate
load:
	$(PY) -m data.generators.run --seed $${SEED:-42}
etl:
	$(PY) -m pipelines.transform.run
quality:
	$(PY) -m pipelines.quality.run
data: pg-start migrate load etl quality
test:
	$(PY) -m pytest -m "not live_gemini" -q
