"""Query-time embedding wrapper for the search module (Phase 3D).

This module is a thin adapter around ``app.resolution.embeddings``.  It exposes
the same ``embed_texts`` function under the search namespace so that the indexer
and retriever can import from ``app.search.embedder`` without hard-coupling to
the resolution package name — but it deliberately does NOT load a second model.
The singleton in ``resolution.embeddings`` is the one and only instance.

Calling pattern (matches resolution/resolver.py):
    vector = await asyncio.to_thread(embed_query, query_str)
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import numpy as np

from app.resolution.embeddings import embed_texts

if TYPE_CHECKING:
    pass


async def embed_query(text: str) -> np.ndarray:
    """Embed a single query string; returns a 1-D (384,) float32 normalised vector.

    Offloads to a thread pool (sentence-transformers is synchronous) so callers
    in async context do not block the event loop.
    """
    vectors = await asyncio.to_thread(embed_texts, [text])
    return vectors[0]


async def embed_batch(texts: list[str]) -> np.ndarray:
    """Embed a batch of strings; returns a (N, 384) float32 array.

    Used by the indexer.  Mirrors ``asyncio.to_thread(embed_texts, ...)`` in
    ``resolution/resolver.py`` — same pattern, same model.
    """
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    return await asyncio.to_thread(embed_texts, texts)
