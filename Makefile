# Shortcuts for local development. Recipes stay simple so they run in cmd, PowerShell and CI (Linux).
API = uv run --directory apps/api

.PHONY: setup dev db-up db-down migrate refresh compare test lint format

setup:
	uv sync --directory apps/api
	$(API) pre-commit install

dev:
	$(API) uvicorn depguard.main:app --reload

db-up:
	docker compose up -d --wait

db-down:
	docker compose down

# Postgres tables, roles and policies; then the role passwords from DATABASE_URL / REFRESH_DATABASE_URL.
migrate:
	$(API) alembic upgrade head
	$(API) python -m depguard.db.set_role_passwords

# Daily KEV/EPSS refresh and rescoring, as the depguard_refresh role.
refresh:
	$(API) python -m depguard.jobs.daily_refresh

# Our findings vs OSV-Scanner on the same lockfiles (needs osv-scanner installed).
# Default: the fixture lockfiles. Example: make compare ARGS="--repo snyk-labs/nodejs-goof"
compare:
	$(API) python scripts/compare_osv_scanner.py $(ARGS)

test:
	$(API) pytest

lint:
	$(API) ruff check
	$(API) ruff format --check
	$(API) mypy

format:
	$(API) ruff check --fix
	$(API) ruff format
