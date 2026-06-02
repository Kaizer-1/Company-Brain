"""Embedding wrapper + per-type input formatters.

The two model-dependent tests load BAAI/bge-small-en-v1.5 and skip gracefully if the model
cannot be loaded (offline CI without the cached weights). The formatter tests are pure.
"""

from __future__ import annotations

import pytest

from app.models.enums import NodeType
from app.resolution.embeddings import node_embedding_input
from app.resolution.models import ResolvableNode


def _try_embed(texts: list[str]):  # type: ignore[no-untyped-def]
    from app.resolution.embeddings import embed_texts

    try:
        return embed_texts(texts)
    except Exception as exc:  # pragma: no cover - offline guard
        pytest.skip(f"embedding model unavailable: {exc}")


def test_identical_strings_have_similarity_one() -> None:
    from app.resolution.embeddings import cosine_similarity

    vectors = _try_embed(["auth-service", "auth-service"])
    assert cosine_similarity(vectors[0], vectors[1]) == pytest.approx(1.0, abs=1e-4)


def test_unrelated_strings_have_low_similarity() -> None:
    from app.resolution.embeddings import cosine_similarity

    vectors = _try_embed(
        ["the quick brown fox jumps over the lazy dog", "quarterly revenue grew by twelve percent"]
    )
    assert cosine_similarity(vectors[0], vectors[1]) < 0.5


def test_person_input_format() -> None:
    node = ResolvableNode(
        node_type=NodeType.Person,
        node_id="alice-chen",
        properties={"display_name": "Alice Chen", "handle": "@alice", "email": "alice.chen@northwind.io"},
    )
    assert node_embedding_input(node) == "Alice Chen|@alice|alice.chen@northwind.io"


def test_person_input_falls_back_to_node_id() -> None:
    node = ResolvableNode(node_type=NodeType.Person, node_id="al")
    assert node_embedding_input(node) == "al"


def test_service_input_includes_aliases() -> None:
    node = ResolvableNode(
        node_type=NodeType.Service,
        node_id="auth-service",
        properties={"canonical_name": "auth-service", "aliases": ["AuthSvc", "the auth service"]},
    )
    assert node_embedding_input(node) == "auth-service|AuthSvc the auth service"


def test_decision_input_uses_id_and_title() -> None:
    node = ResolvableNode(
        node_type=NodeType.Decision, node_id="D-0006", properties={"title": "Deprecate legacy-auth"}
    )
    assert node_embedding_input(node) == "D-0006|Deprecate legacy-auth"
