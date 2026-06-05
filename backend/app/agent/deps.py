"""Runtime dependencies threaded into the agent nodes (Phase 4A).

LangGraph nodes receive only the state. Everything else a node needs — the LLM client,
the config, and the two database handles — is bound into the node at graph-assembly time
via ``functools.partial`` (see graph.py). ``AgentDeps`` is the bundle that gets bound.

The two DB handles mirror the split the tools require: the four KQ functions take the
Neo4j ``AsyncDriver`` directly, while ``hybrid_search`` needs both an Async Postgres
session and the driver.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neo4j import AsyncDriver
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.agent.config import AgentConfig
    from app.extraction.client import OpenRouterClient


@dataclass(frozen=True)
class AgentDeps:
    """Dependencies bound into every node. One instance per ``run_agent`` invocation."""

    client: OpenRouterClient
    config: AgentConfig
    neo4j_driver: AsyncDriver
    session_factory: async_sessionmaker[AsyncSession]
