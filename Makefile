.PHONY: help test install clean build release dev-install lint format check sync-templates render-templates test-e2e test-e2e-sdk test-integration

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
	@echo "  sync-templates Sync .claude/ into src/ templates"
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
test:
	pytest

test-cov:
	pytest --cov=mapify_cli --cov-report=html --cov-report=term

test-watch:
	pytest-watch

# E2E / Integration testing
test-e2e:
	pytest tests/integration/test_e2e_artifact_contracts.py -v

test-e2e-sdk:
	pytest tests/integration/test_e2e_claude_sdk.py -v -m slow

test-integration:
	pytest tests/integration/ -v -m "not slow"

# Code quality
lint:
	ruff check src/ tests/
	mypy src/
	pyright src/
	python3 scripts/lint-hooks.py

format:
	black src/ tests/
	ruff check --fix src/ tests/

check: lint test

sync-templates:
	./scripts/sync-templates.sh

render-templates: ## Render templates_src/*.jinja into all generated trees (dev only)
	uv run python -m mapify_cli.delivery.template_renderer claude
	uv run python -m mapify_cli.delivery.template_renderer codex
	@echo "✅ Templates rendered"

# Build and release
clean:
	rm -rf build/ dist/ *.egg-info/
	rm -rf .pytest_cache/ .coverage htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

build: clean
	python3 -m build

release: build
	@echo "Ready to upload to PyPI with: twine upload dist/*"
	@echo "Don't forget to tag the release: git tag -a v$(shell python3 -c "import tomli; print(tomli.load(open('pyproject.toml', 'rb'))['project']['version'])") -m 'Release version ...'"

# Quick test of the CLI
test-cli:
	@echo "Testing CLI installation..."
	python3 -m mapify_cli --version
	python3 -m mapify_cli check
