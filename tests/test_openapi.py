"""Contract guard: the OpenAPI schema must match the committed snapshot.

Regenerate the snapshot deliberately after an intentional API change:

    UPDATE_OPENAPI_SNAPSHOT=1 uv run pytest tests/test_openapi.py
"""

import json
import os
from pathlib import Path

from app.main import app

SNAPSHOT = Path(__file__).parent / "openapi_snapshot.json"


def render_schema() -> str:
    """Serialize the live OpenAPI schema deterministically."""
    return (
        json.dumps(app.openapi(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    )


def test_openapi_matches_snapshot() -> None:
    """Fail when the HTTP contract drifted without an explicit regeneration."""
    current = render_schema()
    if os.environ.get("UPDATE_OPENAPI_SNAPSHOT") == "1":
        SNAPSHOT.write_text(current)
    assert SNAPSHOT.exists(), "snapshot missing; regenerate it (see module docstring)"
    assert current == SNAPSHOT.read_text(), (
        "OpenAPI schema changed; review the diff and regenerate the snapshot"
    )
