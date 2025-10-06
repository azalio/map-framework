.PHONY: help test install clean build release dev-install lint format check

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

# Code quality
lint:
	ruff check src/ tests/
	mypy src/

format:
	black src/ tests/
	ruff check --fix src/ tests/

check: lint test

# Build and release
clean:
	rm -rf build/ dist/ *.egg-info/
	rm -rf .pytest_cache/ .coverage htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

build: clean
	python -m build

release: build
	@echo "Ready to upload to PyPI with: twine upload dist/*"
	@echo "Don't forget to tag the release: git tag -a v$(shell python -c "import tomli; print(tomli.load(open('pyproject.toml', 'rb'))['project']['version'])") -m 'Release version ...'"

# Quick test of the CLI
test-cli:
	@echo "Testing CLI installation..."
	python -m mapify_cli --version
	python -m mapify_cli check