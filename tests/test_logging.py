"""Tests for application-level logging and error handling."""

import json
import logging

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.main import (
    _configure_logging,
    _JsonFormatter,
    integrity_error_handler,
    unhandled_exception_handler,
)


def test_json_formatter_emits_json() -> None:
    formatter = _JsonFormatter()
    record = logging.LogRecord(
        name="app.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    record.request_id = "rid-123"
    out = formatter.format(record)
    data = json.loads(out)
    assert data["level"] == "INFO"
    assert data["message"] == "hello world"
    assert data["request_id"] == "rid-123"

    # exc_info branch
    try:
        raise ValueError("boom")
    except ValueError:
        record2 = logging.LogRecord(
            name="app.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="err",
            args=(),
            exc_info=__import__("sys").exc_info(),
        )
        record2.request_id = "r2"
        out2 = formatter.format(record2)
        data2 = json.loads(out2)
        assert "exc_info" in data2
        assert "boom" in data2["exc_info"]


def test_configure_logging_respects_existing_handlers() -> None:
    root = logging.getLogger()
    assert root.handlers
    _configure_logging()


def test_probe_requests_log_at_debug(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="app.main"):
        client.get("/healthz")
    probes = [r for r in caplog.records if "GET /healthz ->" in r.getMessage()]
    assert probes, "probe request must be logged"
    assert all(r.levelno == logging.DEBUG for r in probes)


def test_api_requests_log_at_info(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.main"):
        client.get("/api/campaigns")
    lines = [r for r in caplog.records if "GET /api/campaigns ->" in r.getMessage()]
    assert lines, "api request must be logged"
    assert all(r.levelno == logging.INFO for r in lines)


def test_lifespan_demotes_uvicorn_access_log(client: TestClient) -> None:
    assert logging.getLogger("uvicorn.access").level == logging.WARNING


@pytest.mark.anyio
async def test_integrity_error_handler_returns_409(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from sqlalchemy.exc import IntegrityError

    request = Request({"type": "http", "method": "POST", "path": "/x", "headers": []})
    exc = IntegrityError("stmt", {}, Exception("dup"))
    with caplog.at_level(logging.WARNING, logger="app.main"):
        response = await integrity_error_handler(request, exc)
    assert response.status_code == 409
    assert "integrity violation" in caplog.text


@pytest.mark.anyio
async def test_unhandled_exception_handler_logs_and_returns_500(
    caplog: pytest.LogCaptureFixture,
) -> None:
    request = Request({"type": "http", "method": "GET", "path": "/boom", "headers": []})
    exc = RuntimeError("kaboom")
    with caplog.at_level(logging.ERROR, logger="app.main"):
        response = await unhandled_exception_handler(request, exc)
    assert isinstance(response, JSONResponse)
    assert response.status_code == 500
    assert "unhandled exception" in caplog.text
    assert "kaboom" in caplog.text
