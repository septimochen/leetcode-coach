.PHONY: help sync build check format format-check lint typecheck test run fetch-progress

.DEFAULT_GOAL := help

help:
	@echo "Available targets:"
	@echo "  sync            Install project and development dependencies"
	@echo "  build           Build source and wheel distributions"
	@echo "  check           Run lint, type, and test checks"
	@echo "  format          Format Python files with Ruff"
	@echo "  format-check    Check Python formatting with Ruff"
	@echo "  lint            Check Python files with Ruff"
	@echo "  typecheck       Check types with ty"
	@echo "  test            Run the test suite"
	@echo "  run             Generate a weekly plan"
	@echo "  fetch-progress  Refresh cached LeetCode progress"

sync:
	uv sync --group dev

build:
	uv build

check: lint typecheck test

format:
	uv run ruff format .

format-check:
	uv run ruff format --check .

lint:
	uv run ruff check .

typecheck:
	uv run ty check .

test:
	uv run pytest

run:
	uv run leetcode-coach

fetch-progress:
	uv run fetch-progress
