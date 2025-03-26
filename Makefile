.PHONY: sort
sort: 
	isort .

.PHONY: format
format: 
	uv run ruff format

.PHONY: lint
lint:
	uv run ruff check

.PHONY: mypy
mypy: 
	uv run mypy . --check-untyped-defs

.PHONY: test
test:
	pytest

.PHONY: test-verbose
test-verbose:
	pytest -v

.PHONY: test-coverage
test-coverage:
	pytest --cov=async_limiter --cov-report=term --cov-report=html

.PHONY: test-unit
test-unit:
	pytest tests/test_async_limiter.py -v

.PHONY: test-integration
test-integration:
	pytest tests/test_integration.py -v

.PHONY: ci
ci: lint mypy test-coverage

.PHONY: qa
qa: sort format lint test