"""Unit tests for the contradiction detector's pure helpers (Phase 3B; ADR 0019)."""

from __future__ import annotations

from app.contradiction.detector import build_messages, is_candidate, parse_verdict


def test_candidate_on_decision_id_mention() -> None:
    content = "re D-0005: that's not what we're doing anymore"
    assert is_candidate(content, decision_id="D-0005", subjects=["legacy-auth"])


def test_no_candidate_when_id_absent_and_no_cue() -> None:
    content = "legacy-auth is humming along fine"  # mentions subject, no opposition cue
    assert not is_candidate(content, decision_id="D-0005", subjects=["legacy-auth"])


def test_candidate_on_subject_plus_opposition_cue() -> None:
    content = "we should not put new integrations on legacy-auth, it's deprecated"
    assert is_candidate(content, decision_id="D-0005", subjects=["legacy-auth"])


def test_decision_id_word_boundary() -> None:
    # "D-00051" must not match a candidate for D-0005.
    assert not is_candidate("about D-00051 stuff", decision_id="D-0005", subjects=[])


def test_build_messages_includes_decision_and_text() -> None:
    msgs = build_messages("we use auth-service now", decision_id="D-0005", title="stay on legacy-auth")
    assert msgs[0]["role"] == "system"
    assert "D-0005" in msgs[1]["content"]
    assert "auth-service now" in msgs[1]["content"]


def test_parse_verdict_handles_fenced_json() -> None:
    verdict = parse_verdict('```json\n{"contradicts": true, "confidence": 0.9, "reasoning": "x"}\n```')
    assert verdict.contradicts is True
    assert verdict.confidence == 0.9


def test_parse_verdict_falls_back_on_garbage() -> None:
    verdict = parse_verdict("not json at all")
    assert verdict.contradicts is False
    assert verdict.confidence == 0.0
