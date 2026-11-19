.PHONY: run test lint migrate requirements

run:
	uv run python -m app

migrate:
	uv run alembic upgrade head

test:
	uv run pytest --cov=app --cov-report=term-missing --cov-fail-under=100

requirements:
	uv export --locked --no-dev -o requirements.txt

lint:
	uv run ruff check . && uv run ruff format --check . && uv run mypy app tests alembic
