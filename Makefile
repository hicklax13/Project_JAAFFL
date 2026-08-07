.DEFAULT_GOAL := help
.PHONY: help setup setup-backend setup-js backend-dev web-dev ext-dev lint fmt test warehouse clean

## help: list available targets
help:
	@grep -E '^## ' $(MAKEFILE_LIST) | sed 's/## //'

## setup: install backend + JS workspace dependencies
setup: setup-backend setup-js

## setup-backend: install the Python backend (editable, with dev + data + engine extras — matches CI)
setup-backend:
	cd backend && (uv pip install -e '.[dev,data,engine]' || python -m pip install -e '.[dev,data,engine]')

## setup-js: install the pnpm workspace
setup-js:
	pnpm install

## backend-dev: run the FastAPI companion service on 127.0.0.1:8788
backend-dev:
	cd backend && (uv run jaaffl-api || python -m jaaffl.api)

## web-dev: run the Next.js dashboard
web-dev:
	pnpm --filter @jaaffl/web dev

## ext-dev: build the browser extension in watch mode
ext-dev:
	pnpm --filter @jaaffl/extension dev

## lint: lint Python (ruff) and JS (eslint + prettier --check)
lint:
	cd backend && (uv run ruff check . || ruff check .)
	pnpm lint

## fmt: auto-format Python and JS
fmt:
	cd backend && (uv run ruff format . || ruff format .)
	pnpm format

## test: run backend and workspace tests
test:
	cd backend && (uv run pytest || python -m pytest)
	pnpm -r test

## warehouse: rebuild the DISPOSABLE DuckDB analytics store from Parquet + SQLite (never touches app.sqlite)
warehouse:
	cd backend && (uv run python -c "from jaaffl.data.warehouse import rebuild_warehouse; rebuild_warehouse()" \
		|| python -c "from jaaffl.data.warehouse import rebuild_warehouse; rebuild_warehouse()")

## clean: remove build/cache artifacts (keeps data/ contents)
clean:
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
	rm -rf backend/.pytest_cache backend/.ruff_cache backend/.mypy_cache
	rm -rf apps/*/dist apps/*/.next packages/*/dist **/*.tsbuildinfo
