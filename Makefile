.DEFAULT_GOAL := help
SHELL := /bin/bash

.PHONY: install dev lint format test clean check help

install:        ## Install in dev mode (editable)
	uv sync

dev:            ## Install with dev dependencies
	uv sync --group dev

lint:           ## Run linter
	uv run ruff check src/ tests/

format:         ## Auto-format code
	uv run ruff format src/ tests/

check:          ## Lint + format check (CI-friendly)
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

test:           ## Run tests
	uv run pytest tests/ -v

clean:          ## Clean build artifacts
	rm -rf dist/ build/ *.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

help:           ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'
