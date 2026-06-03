"""Demo CLI: run all four killer queries against the live graph and print answers + provenance.

    uv run python backend/scripts/run_killer_queries.py

Assumes the graph is already populated and resolved (run extract_all.py, resolve_entities.py,
consolidate_decisions.py, then the temporal/contradiction passes — or run_query_eval.py for the
whole pipeline). This is the shape of the eventual Phase 3C / agent demo: every answer ties back
to the source events that justify it.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import structlog  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.neo4j_client import Neo4jClient  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.queries.kq1_multihop_ownership import find_chain_owner  # noqa: E402
from app.queries.kq2_temporal_contradiction import find_contradictions  # noqa: E402
from app.queries.kq3_blast_radius import compute_blast_radius  # noqa: E402
from app.queries.kq4_change_tracking import track_changes  # noqa: E402

log = structlog.get_logger(__name__)


def _p(text: str) -> None:
    print(text)  # noqa: T201 - CLI output


async def _run(decision_id: str, service: str, target: str) -> None:
    neo4j = Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    try:
        driver = neo4j.driver

        _p("\n=== KQ1: Multi-hop Ownership ===")
        _p(f"Question: Who owns the service depending on the system deprecated by {decision_id}?")
        kq1 = await find_chain_owner(driver, decision_id=decision_id)
        _p(f"Answer: owners={kq1.value.owner_people}")
        for chain in kq1.value.chains:
            _p(f"  Chain ({chain.hops} hops): {' -> '.join(chain.nodes)}")
        _p(f"Provenance events: {kq1.provenance.all_event_ids}")

        _p("\n=== KQ2: Temporal Contradiction ===")
        _p("Question: Which active decisions are contradicted by discussions in the last 30 days?")
        kq2 = await find_contradictions(driver, window=timedelta(days=30))
        for c in kq2.value:
            _p(f"  {c.decision_id} ({c.decision_title}) — {len(c.messages)} contradicting message(s)")
        _p(f"Provenance events: {kq2.provenance.all_event_ids}")

        _p("\n=== KQ3: Blast Radius ===")
        _p(f"Question: If {service} fails, which services/people/decisions are affected?")
        kq3 = await compute_blast_radius(driver, service_name=service, max_depth=5)
        _p(f"Affected services ({len(kq3.value.affected_services)}): {kq3.value.affected_services}")
        _p(f"Affected people: {kq3.value.affected_people}")
        _p(f"Affected decisions: {kq3.value.affected_decisions}")
        _p(f"Max depth reached: {kq3.value.max_depth_reached}")

        _p("\n=== KQ4: Change Tracking ===")
        _p(f"Question: What changed about {target} in the last quarter, and who approved each?")
        kq4 = await track_changes(driver, target_name=target, window=timedelta(days=90))
        for ch in kq4.value.changes:
            sup = f" (supersedes {ch.supersedes})" if ch.supersedes else ""
            _p(f"  {ch.decision_id} [{ch.status}] {ch.title} — approved by {ch.approvers}{sup}")
        _p(f"Provenance events: {kq4.provenance.all_event_ids}")
    finally:
        await neo4j.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run all four killer queries with provenance.")
    parser.add_argument("--decision-id", default="D-0006")
    parser.add_argument("--service", default="payments-api")
    parser.add_argument("--target", default="auth-service")
    args = parser.parse_args()

    configure_logging(debug=settings.debug)
    asyncio.run(_run(args.decision_id, args.service, args.target))


if __name__ == "__main__":
    main()
