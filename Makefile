# AHIA developer entry point.
#
# Every target is a thin wrapper over a real script or tool. There is no hidden
# logic here on purpose: if a target does something, you can read the script it
# calls and reproduce the command by hand.
#
# The one command that matters:
#     make check      run every gate that CI runs
#
# Repository layout: backend/ holds the Python service. web/ and mobile/ are
# created by later milestones; their targets are added when those workspaces
# exist rather than being stubbed now.

SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

REPOSITORY_ROOT := $(shell cd "$(dir $(lastword $(MAKEFILE_LIST)))" && pwd)
BACKEND_DIR := $(REPOSITORY_ROOT)/backend
VENV_DIR := $(BACKEND_DIR)/.venv
PYTHON := $(VENV_DIR)/bin/python
PIP := $(VENV_DIR)/bin/pip
PRE_COMMIT := $(VENV_DIR)/bin/pre-commit

# The default database for local development. Tests use a separate database so
# a test run can never truncate development data.
DATABASE_URL ?= postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_dev
TEST_DATABASE_URL ?= postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test
export DATABASE_URL
export TEST_DATABASE_URL

.PHONY: help setup hooks check check-fast lint format typecheck test test-unit \
        test-integration arch secrets secrets-history audit ascii banned-names \
        guards run migrate revision downgrade load-smoke clean tools

help: ## Show this help
	@printf 'AHIA developer commands\n\n'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'
	@printf '\nRun "make check" before every commit.\n'

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

setup: ## Create the virtual environment and install the locked dependencies
	@bash $(BACKEND_DIR)/scripts/bootstrap_backend.sh

tools: ## Install the checksum-verified workspace tools (secret scanner)
	@bash $(BACKEND_DIR)/scripts/install_workspace_tools.sh

hooks: ## Install the pre-commit hooks into .git/hooks
	@bash $(BACKEND_DIR)/scripts/install_git_hooks.sh

# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

check: ## Run every gate: format, lint, types, guards, tests, arch, secrets, audit
	@bash $(BACKEND_DIR)/scripts/dev_check.sh

check-fast: ## Run every gate except the dependency audit (offline-friendly)
	@bash $(BACKEND_DIR)/scripts/dev_check.sh --skip-audit

# ---------------------------------------------------------------------------
# Individual gates
# ---------------------------------------------------------------------------

lint: ## Lint the backend
	@cd $(BACKEND_DIR) && $(VENV_DIR)/bin/ruff check .

format: ## Format the backend
	@cd $(BACKEND_DIR) && $(VENV_DIR)/bin/ruff format .
	@cd $(BACKEND_DIR) && $(VENV_DIR)/bin/ruff check --fix .

typecheck: ## Type check the backend
	@cd $(BACKEND_DIR) && $(VENV_DIR)/bin/mypy

test: ## Run the full test suite with coverage
	@cd $(BACKEND_DIR) && $(VENV_DIR)/bin/pytest

test-unit: ## Run only the unit tests
	@cd $(BACKEND_DIR) && $(VENV_DIR)/bin/pytest -m unit

test-integration: ## Run only the tests that need the test database
	@cd $(BACKEND_DIR) && $(VENV_DIR)/bin/pytest -m integration

arch: ## Enforce the layer dependency contracts
	@cd $(BACKEND_DIR) && $(VENV_DIR)/bin/lint-imports --config import-linter.ini --no-cache

secrets: ## Scan the working tree for secrets
	@bash $(BACKEND_DIR)/scripts/scan_secrets.sh

secrets-history: ## Scan the whole git history for secrets
	@bash $(BACKEND_DIR)/scripts/scan_secrets.sh --history

audit: ## Audit pinned dependencies for known vulnerabilities
	@bash $(BACKEND_DIR)/scripts/audit_dependencies.sh

ascii: ## Fail on emoji or non-ASCII in engineering artifacts
	@$(PYTHON) $(BACKEND_DIR)/scripts/check_ascii.py

banned-names: ## Fail on banned standalone names
	@$(PYTHON) $(BACKEND_DIR)/scripts/check_banned_names.py

guards: ascii banned-names ## Run both code hygiene guards

# ---------------------------------------------------------------------------
# Running the service
# ---------------------------------------------------------------------------

run: ## Run the API with autoreload for local development
	@cd $(BACKEND_DIR) && $(VENV_DIR)/bin/uvicorn ahia.main:app --reload --host 127.0.0.1 --port 8000

migrate: ## Apply all database migrations
	@cd $(BACKEND_DIR) && $(VENV_DIR)/bin/alembic upgrade head

revision: ## Create a migration from the current models (MESSAGE="...")
	@cd $(BACKEND_DIR) && $(VENV_DIR)/bin/alembic revision --autogenerate -m "$(MESSAGE)"

downgrade: ## Roll back one migration
	@cd $(BACKEND_DIR) && $(VENV_DIR)/bin/alembic downgrade -1

load-smoke: ## Record a load smoke test on the sale path (local test database)
	@cd $(BACKEND_DIR) && $(PYTHON) scripts/load_smoke_sale.py --sales 200 --concurrency 20

# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------

clean: ## Remove caches and build output from the working tree
	@find $(BACKEND_DIR) -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
	@rm -rf $(BACKEND_DIR)/.pytest_cache $(BACKEND_DIR)/.mypy_cache $(BACKEND_DIR)/.ruff_cache
	@rm -rf $(BACKEND_DIR)/htmlcov $(BACKEND_DIR)/coverage.xml $(BACKEND_DIR)/.coverage
	@printf '[OK] caches removed\n'
