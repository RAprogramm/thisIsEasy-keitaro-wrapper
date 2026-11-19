"""Tests for application-level logging and error handling."""

import logging

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse

from app.main import _configure_logging, unhandled_exception_handler


def test_configure_logging_respects_existing_handlers() -> None:
    root = logging.getLogger()
    assert root.handlers  # pytest installs handlers
    _configure_logging()  # exercises the early-return branch


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
