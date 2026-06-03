"""Detect CONTRADICTS edges between recent Messages and active Decisions (Phase 3B; ADR 0019).

A *detection job*, not extraction: it runs after extraction/resolution/temporal enrichment.
Candidate (Message, Decision) pairs are generated where a recent message names a decision id, or
names a subject the decision is ABOUT/DEPRECATES *and* carries an opposition cue. Each candidate
is adjudicated by ``claude-3.5-haiku`` (the 3A adjudicator model); a positive verdict writes
``(m)-[:CONTRADICTS {confidence, extracted_by, source_event_id}]->(d)``. With no client
configured the pass is a conservative no-op — the same fallback the resolver uses.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import TYPE_CHECKING

import structlog
from pydantic import ValidationError

from app.contradiction.models import ContradictionResult, ContradictionVerdict
from app.queries.temporal import resolve_as_of

if TYPE_CHECKING:
    from datetime import datetime

    from neo4j import AsyncDriver

    from app.extraction.client import OpenRouterClient

log = structlog.get_logger(__name__)

ADJUDICATOR_MODEL = "anthropic/claude-3.5-haiku"
_JSON_RESPONSE_FORMAT = {"type": "json_object"}
DETECTION_WINDOW = timedelta(days=60)
_EXTRACTED_BY = "contradiction-detector@3b"
_CONTENT_CHARS = 500

# Words that signal a message is pushing back on a stated position. Used to gate the
# subject-mention candidate branch so we don't adjudicate every message about a subject.
_OPPOSITION_CUES = (
    "not ", "n't", "should not", "stale", "deprecated", "stop ", "no longer",
    "instead", "contradic", "disagree", "shouldn", "don't", "won't",
)

_SYSTEM_PROMPT = (
    "You judge whether a Slack message contradicts a recorded engineering decision. A "
    "contradiction means the message argues for or describes doing the opposite of what the "
    "decision mandates — not merely mentioning the same topic. Be conservative: only answer "
    "true when the message genuinely opposes the decision. Respond with JSON only."
)

_FALLBACK = ContradictionVerdict(
    contradicts=False, confidence=0.0, reasoning="adjudication failed; defaulting to no edge"
)


def _has_opposition_cue(content: str) -> bool:
    lowered = content.lower()
    return any(cue in lowered for cue in _OPPOSITION_CUES)


def is_candidate(message_content: str, *, decision_id: str, subjects: list[str]) -> bool:
    """True if this message is worth adjudicating against this decision.

    A decision-id mention is a strong signal on its own; a subject mention only qualifies when
    the message also carries an opposition cue, to bound candidate volume and cost.
    """
    if re.search(rf"\b{re.escape(decision_id)}\b", message_content):
        return True
    lowered = message_content.lower()
    return any(subj.lower() in lowered for subj in subjects) and _has_opposition_cue(
        message_content
    )


def build_messages(message_content: str, *, decision_id: str, title: str) -> list[dict[str, str]]:
    """Assemble the chat messages for one adjudication. Pure — easy to assert in tests."""
    user = (
        f"Decision {decision_id}: {title}\n\n"
        f"Slack message:\n{message_content.strip()[:_CONTENT_CHARS]}\n\n"
        f"Does the message contradict decision {decision_id}? Respond with JSON:\n"
        '{\n'
        '  "contradicts": true | false,\n'
        '  "confidence": 0.0-1.0,\n'
        '  "reasoning": "brief explanation grounded in the message text"\n'
        '}'
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def parse_verdict(content: str) -> ContradictionVerdict:
    """Parse the model's JSON into a verdict, or fall back to no-edge (never raises)."""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return ContradictionVerdict.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        log.warning("contradiction_parse_failure", error=str(exc)[:200], raw=content[:200])
        return _FALLBACK


class ContradictionAdjudicator:
    """LLM adjudicator for one (message, decision) pair. Reuses the OpenRouter client."""

    def __init__(self, client: OpenRouterClient, *, model: str = ADJUDICATOR_MODEL) -> None:
        self._client = client
        self._model = model
        self.cost_usd = 0.0

    @property
    def model(self) -> str:
        return self._model

    async def adjudicate(
        self, *, message_content: str, decision_id: str, title: str
    ) -> ContradictionVerdict:
        """Ask the LLM whether the message contradicts the decision. Never raises."""
        messages = build_messages(message_content, decision_id=decision_id, title=title)
        try:
            completion = await self._client.complete(
                messages=messages, model=self._model, response_format=_JSON_RESPONSE_FORMAT
            )
        except Exception as exc:  # noqa: BLE001 - a failed call must not abort the run
            log.warning("contradiction_call_failed", error=str(exc)[:200])
            return _FALLBACK
        self.cost_usd += completion.cost_usd
        return parse_verdict(completion.content)


async def detect_contradictions(
    driver: AsyncDriver,
    *,
    client: OpenRouterClient | None = None,
    as_of: datetime | None = None,
    window: timedelta = DETECTION_WINDOW,
) -> ContradictionResult:
    """Generate candidates, adjudicate, and write CONTRADICTS edges; return a report."""
    effective = resolve_as_of(as_of)
    window_start = effective - window
    decisions = await _load_active_decisions(driver)
    messages = await _load_recent_messages(driver, window_start, effective)

    candidates: list[tuple[dict[str, object], dict[str, object]]] = []
    for msg in messages:
        content = str(msg["content"])
        for dec in decisions:
            subjects_val = dec.get("subjects")
            subjects = [str(s) for s in subjects_val] if isinstance(subjects_val, list) else []
            if is_candidate(content, decision_id=str(dec["id"]), subjects=subjects):
                candidates.append((msg, dec))

    result = ContradictionResult(messages_ingested=len(messages), candidate_pairs=len(candidates))
    if client is None:
        log.info("contradiction_no_client", candidates=len(candidates))
        return result

    adjudicator = ContradictionAdjudicator(client)
    for msg, dec in candidates:
        verdict = await adjudicator.adjudicate(
            message_content=str(msg["content"]),
            decision_id=str(dec["id"]),
            title=str(dec.get("title") or ""),
        )
        if verdict.contradicts:
            await _write_contradicts(
                driver,
                message_id=str(msg["id"]),
                decision_id=str(dec["id"]),
                confidence=verdict.confidence,
                source_event_id=_first_event(msg),
            )
            result.contradicts_written += 1
    result.llm_cost_usd = adjudicator.cost_usd
    log.info(
        "contradiction_detection_complete",
        candidates=result.candidate_pairs,
        written=result.contradicts_written,
        cost_usd=round(result.llm_cost_usd, 4),
    )
    return result


def _first_event(msg: dict[str, object]) -> str | None:
    ids = msg.get("source_event_ids")
    if isinstance(ids, (list, tuple)) and ids:
        return str(ids[0])
    return None


async def _load_active_decisions(driver: AsyncDriver) -> list[dict[str, object]]:
    """Active, non-merged decisions with their ABOUT/DEPRECATES subject names."""
    query = (
        "MATCH (d:Decision) WHERE coalesce(d.status,'active') = 'active' "
        "OPTIONAL MATCH (d)-[:ABOUT|DEPRECATES]->(s) "
        "WHERE coalesce(s.status,'active') <> 'merged' "
        "RETURN d.id AS id, d.title AS title, "
        "  collect(DISTINCT coalesce(s.canonical_name, s.id)) AS subjects"
    )
    out: list[dict[str, object]] = []
    async with driver.session() as session:
        result = await session.run(query)
        async for record in result:
            out.append(
                {
                    "id": record["id"],
                    "title": record["title"],
                    "subjects": [s for s in record["subjects"] if s],
                }
            )
    return out


async def _load_recent_messages(
    driver: AsyncDriver, window_start: datetime, as_of: datetime
) -> list[dict[str, object]]:
    """Non-merged Message nodes whose created_at falls within the detection window."""
    query = (
        "MATCH (m:Message) WHERE coalesce(m.status,'active') <> 'merged' "
        "  AND m.created_at >= datetime($start) AND m.created_at <= datetime($end) "
        "RETURN m.id AS id, m.content AS content, m.source_event_ids AS source_event_ids"
    )
    out: list[dict[str, object]] = []
    async with driver.session() as session:
        result = await session.run(query, start=window_start.isoformat(), end=as_of.isoformat())
        async for record in result:
            out.append(
                {
                    "id": record["id"],
                    "content": record["content"],
                    "source_event_ids": record["source_event_ids"],
                }
            )
    return out


async def _write_contradicts(
    driver: AsyncDriver,
    *,
    message_id: str,
    decision_id: str,
    confidence: float,
    source_event_id: str | None,
) -> None:
    """MERGE the CONTRADICTS edge with extraction metadata, idempotently."""
    query = (
        "MATCH (m:Message {id: $mid}) MATCH (d:Decision {id: $did}) "
        "MERGE (m)-[r:CONTRADICTS]->(d) "
        "ON CREATE SET r.created_at = datetime() "
        "SET r.confidence = $confidence, r.extracted_by = $extracted_by, "
        "    r.source_event_id = $source_event_id"
    )
    async with driver.session() as session:
        await (
            await session.run(
                query,
                mid=message_id,
                did=decision_id,
                confidence=confidence,
                extracted_by=_EXTRACTED_BY,
                source_event_id=source_event_id,
            )
        ).consume()
