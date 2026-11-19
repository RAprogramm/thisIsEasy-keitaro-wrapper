.PHONY: run test lint migrate

run:
	uv run python -m app

migrate:
	uv run alembic upgrade head

test:
	uv run pytest --cov=app --cov-fail-under=100

lint:
	uv run ruff check . && uv run ruff format --check . && uv run mypy app tests alembic
