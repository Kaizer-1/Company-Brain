"""Real Neo4j + Postgres test for Decision consolidation (Phase 3B; ADR 0017).

Embeddings are monkeypatched to deterministic vectors keyed on title content, so the test runs
without downloading the sentence-transformers model and asserts the *consolidation logic*
(threshold + authority guard + MERGE_INTO + audit row), not embedding quality.
"""

from __future__ import annotations

import numpy as np
import pytest
from sqlalchemy import text

from app.resolution.consolidator import consolidate_decisions

pytestmark = pytest.mark.asyncio


def _fake_embed(texts: list[str]) -> np.ndarray:
    """Map each text to a one-hot vector by keyword so similar titles get identical vectors."""
    rows = []
    for t in texts:
        low = t.lower()
        if "jwt" in low:
            rows.append([1.0, 0.0, 0.0])
        elif "harden" in low:
            rows.append([0.0, 1.0, 0.0])
        else:
            rows.append([0.0, 0.0, 1.0])
    return np.asarray(rows, dtype=np.float32)


_SEED = """
CREATE (:Decision {id:'D-0010', title:'move auth to jwt', status:'active', source_event_ids:['e1','e2']})
CREATE (:Decision {id:'the-jwt-cutover', title:'move auth to jwt', status:'active', source_event_ids:['e3']})
CREATE (:Decision {id:'D-0007', title:'auth harden mtls', status:'active', source_event_ids:['e4']})
CREATE (:Decision {id:'D-0008', title:'auth harden keys', status:'active', source_event_ids:['e5']})
"""


async def test_consolidator_merges_paraphrase_not_distinct_formal_ids(
    neo4j_driver: object, db_session: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.resolution.consolidator.embed_texts", _fake_embed)
    async with neo4j_driver.session() as s:  # type: ignore[attr-defined]
        await (await s.run(_SEED)).consume()

    counts = await consolidate_decisions(neo4j_driver, db_session)  # type: ignore[arg-type]
    await db_session.commit()  # type: ignore[attr-defined]

    assert counts["merges"] == 1  # only the paraphrase pair; the two formal ids are guarded

    async with neo4j_driver.session() as s:  # type: ignore[attr-defined]
        # The paraphrase node (fewer events) was tombstoned and linked to the formal D-0010.
        rec = await (
            await s.run(
                "MATCH (l:Decision {id:'the-jwt-cutover'})-[:MERGE_INTO]->(w:Decision {id:'D-0010'}) "
                "RETURN l.status AS st"
            )
        ).single()
        assert rec is not None
        assert rec["st"] == "merged"
        # The two distinct formal decisions stayed separate.
        guard = await (
            await s.run(
                "MATCH (a:Decision {id:'D-0007'}), (b:Decision {id:'D-0008'}) "
                "RETURN coalesce(a.status,'active') AS sa, coalesce(b.status,'active') AS sb"
            )
        ).single()
        assert guard["sa"] == "active"
        assert guard["sb"] == "active"

    # An audit row with decision='content_merge' was written.
    row = await db_session.execute(  # type: ignore[attr-defined]
        text("SELECT count(*) FROM merge_decisions WHERE decision = 'content_merge'")
    )
    assert row.scalar_one() == 1
