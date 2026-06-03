"""Unit tests for the supersession text detector (Phase 3B; ADR 0016)."""

from __future__ import annotations

from app.temporal.supersession import detect_superseded_target


def test_detects_supersedes_with_id() -> None:
    text = "auth-service moves to stateless JWT, superseding the D-0004 session model."
    assert detect_superseded_target([text], self_id="D-0010") == "D-0004"


def test_detects_plain_supersedes() -> None:
    assert detect_superseded_target(["This supersedes D-0004."], self_id="D-0010") == "D-0004"


def test_ignores_self_reference() -> None:
    # A decision quoting its own id in a supersedes-like phrase must not supersede itself.
    assert detect_superseded_target(["D-0004 supersedes D-0004"], self_id="D-0004") is None


def test_returns_none_when_absent() -> None:
    assert detect_superseded_target(["auth-service ships JWT support"], self_id="D-0010") is None


def test_scans_multiple_texts() -> None:
    texts = ["unrelated message", "ADR notes: supersedes D-0002"]
    assert detect_superseded_target(texts, self_id="D-0009") == "D-0002"
