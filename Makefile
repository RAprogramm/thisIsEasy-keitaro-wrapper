.PHONY: run setup test lint verify migrate requirements audit

run:
	uv run python -m app

setup:
	uv sync
	-createdb keitaro
	-createdb keitaro_test
	uv run alembic upgrade head

migrate:
	uv run alembic upgrade head

test:
	uv run pytest --cov=app --cov-report=term-missing --cov-fail-under=100

requirements:
	uv export --locked --no-dev -o requirements.txt

lint:
	uv run ruff check . && uv run ruff format --check . && uv run mypy app tests alembic && uv run yamllint .github docker-compose.yml && uv run deptry app tests alembic && uv run typos

verify: lint test

audit:
	uv run pip-audit --skip-editable
