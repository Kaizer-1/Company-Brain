"""Local sentence-transformers embeddings for entity resolution (Phase 3A).

We embed each node into a vector and use cosine similarity as the candidate-pair signal.
The model is ``BAAI/bge-small-en-v1.5``, run locally on CPU and cached in a module-level
singleton so it is loaded once per process (loading is the expensive part). The choice of a
local model over a hosted embedding API is deliberate — free, deterministic, reproducible —
and defended in ADR 0014 and docs/design/entity-resolution.md.

``sentence_transformers`` (and its PyTorch dependency) is imported lazily inside
``_get_model`` so that importing the resolution package — and running the rules/merger tests
— does not require torch to be installed or a model to be downloaded.
"""

from __future__ import annotations

from threading import Lock
from typing import TYPE_CHECKING, Any

import numpy as np
import structlog

if TYPE_CHECKING:
    from app.resolution.models import ResolvableNode

log = structlog.get_logger(__name__)

MODEL_NAME = "BAAI/bge-small-en-v1.5"

_model: Any | None = None
_model_lock = Lock()


def _get_model() -> Any:  # noqa: ANN401 - SentenceTransformer has no type stubs
    """Load (once) and return the cached SentenceTransformer singleton."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer

                log.info("loading_embedding_model", model=MODEL_NAME)
                _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed_texts(texts: list[str]) -> np.ndarray:
    """Embed a batch of strings into L2-normalised row vectors.

    Returns a ``(len(texts), dim)`` float32 array. Normalising at encode time means cosine
    similarity is a plain dot product (``embed_texts(...) @ vec``), which keeps the
    candidate-generation arithmetic trivial.
    """
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    model = _get_model()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vectors, dtype=np.float32)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two vectors, clamped to [-1, 1].

    Works whether or not the inputs are already normalised (it divides by the norms), so it
    is safe to call on raw vectors in tests.
    """
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.clip(np.dot(a, b) / denom, -1.0, 1.0))


def node_embedding_input(node: ResolvableNode) -> str:
    """Build the per-type delimited string we embed for a node.

    Documented in docs/design/entity-resolution.md. Each type leads with the fields that
    vary across that type's aliases; empty fields are dropped and we fall back to the node id
    so every node embeds to *something*.
    """
    from app.models.enums import NodeType

    parts: list[str]
    if node.node_type == NodeType.Person:
        parts = [
            node.prop_str("display_name") or node.node_id,
            node.prop_str("handle") or "",
            node.prop_str("email") or "",
        ]
    elif node.node_type in (NodeType.Service, NodeType.System):
        parts = [node.prop_str("canonical_name") or node.node_id, _aliases_str(node)]
    elif node.node_type == NodeType.Team:
        parts = [
            node.prop_str("canonical_name") or node.node_id,
            node.prop_str("display_name") or "",
        ]
    else:  # Decision
        parts = [node.node_id, node.prop_str("title") or ""]

    nonempty = [p for p in parts if p]
    return "|".join(nonempty) if nonempty else node.node_id


def _aliases_str(node: ResolvableNode) -> str:
    """Space-joined alias list from a node's ``aliases`` property (string or list)."""
    value = node.properties.get("aliases")
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " ".join(str(v) for v in value)
    return ""
