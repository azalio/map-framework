.PHONY: help test install clean build release dev-install lint format check check-render render-templates test-e2e test-e2e-sdk test-integration

# Default target
help:
	@echo "Available targets:"
	@echo "  install      Install the package"
	@echo "  dev-install  Install for development (with test dependencies)"
	@echo "  test         Run test suite"
	@echo "  test-cov     Run tests with coverage"
	@echo "  lint         Run linters"
	@echo "  format       Format code with black"
	@echo "  clean        Clean build artifacts"
	@echo "  build        Build distribution packages"
	@echo "  release      Create a new release"
	@echo "  check        Run all checks (lint + test)"
	@echo "  render-templates Render templates_src/*.jinja into all generated trees (dev only)"
	@echo "  test-e2e     Run e2e artifact contract tests (no LLM, fast)"
	@echo "  test-e2e-sdk Run e2e tests with real Claude SDK (slow, needs API key)"
	@echo "  test-integration Run integration tests (excludes slow SDK tests)"

# Installation
install:
	pip install -e .

dev-install:
	pip install -e ".[dev,ssl]"

# Testing
# Invoke tools via `uv run` so they always use the project venv. A bare
# `pytest`/`ruff`/`pyright` resolves to whatever is first on PATH (e.g. a
# global Homebrew install whose interpreter lacks truststore/hypothesis),
# producing phantom failures that disappear under `uv run`.
test:
	uv run pytest

test-cov:
	uv run pytest --cov=mapify_cli --cov-report=html --cov-report=term

test-watch:
	uv run pytest-watch

# E2E / Integration testing
test-e2e:
	uv run pytest tests/integration/test_e2e_artifact_contracts.py -v

test-e2e-sdk:
	uv run pytest tests/integration/test_e2e_claude_sdk.py -v -m slow

test-integration:
	uv run pytest tests/integration/ -v -m "not slow"

# Code quality
lint:
	uv run ruff check src/ tests/
	uv run mypy src/
	uv run pyright src/
	uv run python3 scripts/lint-hooks.py

format:
	uv run black src/ tests/
	uv run ruff check --fix src/ tests/

check: lint test check-render

render-templates: ## Render templates_src/*.jinja into all generated trees (dev only)
	uv run python -m mapify_cli.delivery.template_renderer claude
	uv run python -m mapify_cli.delivery.template_renderer codex
	@echo "✅ Templates rendered"

check-render: ## Render templates_src and fail if committed generated trees are stale
	# Non-destructive: renders into a tempdir and byte-compares against the
	# committed trees. Never renders in place and never runs `git checkout`,
	# so uncommitted hand-authored files (e.g. .claude/rules/learned/*-patterns.md,
	# invariant D11) are NEVER reverted.
	uv run python -m mapify_cli.delivery.template_renderer --check

# Build and release
clean:
	rm -rf build/ dist/ *.egg-info/
	rm -rf .pytest_cache/ .coverage htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

build: clean
	uv run python3 -m build

release: build
	@echo "Ready to upload to PyPI with: twine upload dist/*"
	@echo "Don't forget to tag the release: git tag -a v$(shell uv run python3 -c "import tomli; print(tomli.load(open('pyproject.toml', 'rb'))['project']['version'])") -m 'Release version ...'"

# Quick test of the CLI
test-cli:
	@echo "Testing CLI installation..."
	uv run python3 -m mapify_cli --version
	uv run python3 -m mapify_cli check
