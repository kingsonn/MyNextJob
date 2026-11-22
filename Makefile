.PHONY: up seed test observability langfuse-hello

COMPOSE := docker compose --env-file deploy/env.example -f deploy/docker-compose.yml

include deploy/env.example

export CLAIMPILOT_DATABASE_URL
export LANGFUSE_HOST
export LANGFUSE_PUBLIC_KEY
export LANGFUSE_SECRET_KEY

up:
	$(COMPOSE) --profile core up -d --wait
	$(MAKE) seed

seed:
	python -m generator seed

test:
	python -m pytest

observability:
	$(COMPOSE) --profile observability up -d --wait

langfuse-hello: observability
	python tools/langfuse_hello.py

