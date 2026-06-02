"""Offline replay of the recorded OpenRouter response — runs in CI without an API key.

Loads the cassette recorded by ``test_real_openrouter_call.py`` and asserts the parser
turns that real response into a non-trivial extraction. This is the "replay the cassette"
half of the record-once/replay-in-CI pattern: it exercises the real model's output shape
against the parser without any network access.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.extraction.parser import parse_extraction

_CASSETTE = Path(__file__).parent / "cassettes" / "openrouter_decision.json"


@pytest.mark.skipif(not _CASSETTE.exists(), reason="no recorded cassette yet")
def test_recorded_response_parses_into_entities() -> None:
    data = json.loads(_CASSETTE.read_text(encoding="utf-8"))
    result = parse_extraction(data["content"])
    assert len(result.entities) >= 1
    # The decision record names a Decision and at least one Service/System.
    types = {e.type for e in result.entities}
    assert "Decision" in types or "Service" in types
