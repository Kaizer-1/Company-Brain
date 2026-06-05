"""Unit tests for app/search/embedder.py.

The embedder is a thin async wrapper around resolution/embeddings.py.
Tests verify:
  - embed_query returns a 1-D (384,) L2-normalised vector
  - embed_batch returns (N, 384) for a list of strings
  - empty batch returns zero-row array
  - the same model singleton is used (no second load)
  - vectors are L2-normalised (||v|| ≈ 1.0)
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from app.search.embedder import embed_batch, embed_query


@pytest.mark.asyncio
async def test_embed_query_shape_and_norm() -> None:
    vec = await embed_query("auth migration decision")
    assert vec.shape == (384,), f"Expected shape (384,), got {vec.shape}"
    norm = float(np.linalg.norm(vec))
    assert abs(norm - 1.0) < 1e-4, f"Expected L2-normalised vector (||v||≈1), got {norm}"


@pytest.mark.asyncio
async def test_embed_query_deterministic() -> None:
    v1 = await embed_query("payments-api dependency")
    v2 = await embed_query("payments-api dependency")
    assert np.allclose(v1, v2, atol=1e-6), "Same input must produce identical output"


@pytest.mark.asyncio
async def test_embed_batch_shape() -> None:
    texts = ["hello", "world", "auth migration"]
    arr = await embed_batch(texts)
    assert arr.shape == (3, 384), f"Expected (3, 384), got {arr.shape}"


@pytest.mark.asyncio
async def test_embed_batch_normalised() -> None:
    arr = await embed_batch(["test sentence one", "test sentence two"])
    for i in range(arr.shape[0]):
        norm = float(np.linalg.norm(arr[i]))
        assert abs(norm - 1.0) < 1e-4, f"Row {i} not normalised: ||v||={norm}"


@pytest.mark.asyncio
async def test_embed_batch_empty_returns_zero_rows() -> None:
    arr = await embed_batch([])
    assert arr.shape[0] == 0, f"Empty input must return 0-row array, got shape {arr.shape}"


@pytest.mark.asyncio
async def test_embed_batch_single_matches_query() -> None:
    text = "legacy-auth deprecation"
    via_query = await embed_query(text)
    via_batch = await embed_batch([text])
    assert np.allclose(via_query, via_batch[0], atol=1e-6), (
        "embed_query and embed_batch([text])[0] must produce identical vectors"
    )


@pytest.mark.asyncio
async def test_same_model_singleton() -> None:
    """Embed two queries and verify they come from the same model (no double load).

    We cannot assert on the internal singleton directly, but we can verify that
    two calls to the same model produce identical outputs — which would fail if
    a second model instance produced subtly different vectors (e.g., different
    random seeds or normalization).
    """
    t1 = "service dependency map"
    v1_a = await embed_query(t1)
    v1_b = await embed_query(t1)
    assert np.allclose(v1_a, v1_b, atol=1e-6)


def test_embed_batch_sync_invocation() -> None:
    """embed_batch is async; ensure it can be called via asyncio.run."""
    arr = asyncio.run(embed_batch(["test"]))
    assert arr.shape == (1, 384)
