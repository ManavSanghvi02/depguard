# Shortcuts for local development. Recipes stay simple so they run in cmd, PowerShell and CI (Linux).
API = uv run --directory apps/api

.PHONY: setup dev db-up db-down test lint format

setup:
	uv sync --directory apps/api
	$(API) pre-commit install

dev:
	$(API) uvicorn depguard.main:app --reload

db-up:
	docker compose up -d --wait

db-down:
	docker compose down

test:
	$(API) pytest

lint:
	$(API) ruff check
	$(API) ruff format --check
	$(API) mypy

format:
	$(API) ruff check --fix
	$(API) ruff format
