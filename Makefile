.PHONY: run demo demo-stop demo-reset setup test lint verify migrate requirements audit

MOCK_PORT := 9001
DEMO_PORT := 8001

run:
	uv run python -m app

demo:
	@curl -sf http://127.0.0.1:$(MOCK_PORT)/openapi.json > /dev/null || \
		(nohup uv run uvicorn --app-dir scripts mock_keitaro:app --host 127.0.0.1 --port $(MOCK_PORT) > /tmp/keitaro-mock.log 2>&1 & sleep 2)
	KEITARO_URL=http://127.0.0.1:$(MOCK_PORT) KEITARO_API_KEY=demo \
		uv run uvicorn app.main:app --host 127.0.0.1 --port $(DEMO_PORT)

demo-stop:
	-fuser -k $(DEMO_PORT)/tcp 2>/dev/null || true
	-fuser -k $(MOCK_PORT)/tcp 2>/dev/null || true

demo-reset:
	-fuser -k $(MOCK_PORT)/tcp 2>/dev/null || true
	sleep 1
	nohup uv run uvicorn --app-dir scripts mock_keitaro:app --host 127.0.0.1 --port $(MOCK_PORT) > /tmp/keitaro-mock.log 2>&1 &
	sleep 2
	set -a; . ./.env; set +a; \
	psql "$$(printf '%s' "$$DATABASE_URL" | sed 's/+psycopg//')" \
		-c "DELETE FROM offer_changes WHERE campaign_id IN (SELECT id FROM campaigns WHERE keitaro_id >= 900000);" \
		-c "DELETE FROM campaigns WHERE keitaro_id >= 900000;" \
		-c "DELETE FROM stream_offers WHERE keitaro_campaign_id >= 900000;"
	@echo "demo stand reset: mock reseeded, demo tracking cleared"

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
