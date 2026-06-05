"""Tunable constants for the hybrid search system (Phase 3D).

All constants are module-level so they can be changed without a code edit — the
backend's ``--reload`` mode and testcontainer runs both pick up the new values on
import.  Per ADR 0022: weights are set by reasoning about the bounding case, not
by training; the documented upgrade path is eval-driven adjustment here.
"""

# ---------------------------------------------------------------------------
# Embedding model (matches resolution/embeddings.py — do not introduce a new one)
# ---------------------------------------------------------------------------
MODEL_NAME = "BAAI/bge-small-en-v1.5"
MODEL_VERSION = "1.0"  # model is local and pinned; bump if the weights change

# ---------------------------------------------------------------------------
# Indexer batch size (mirrors resolution/resolver.py's embed-batch approach)
# ---------------------------------------------------------------------------
EMBED_BATCH_SIZE = 32

# ---------------------------------------------------------------------------
# Retrieval fanout multipliers
#   k            — user-requested top-k results
#   BASE_FANOUT  — candidate pool = BASE_FANOUT * k (no active filter)
#   FILTER_FANOUT— candidate pool = FILTER_FANOUT * k (any filter active)
#                  More headroom after filtering reduces the chance of
#                  running out of candidates before reaching k results.
# ---------------------------------------------------------------------------
BASE_FANOUT = 3
FILTER_FANOUT = 5

# ---------------------------------------------------------------------------
# Reranker blend weights (ADR 0022)
#   W_VEC   — weight for cosine similarity (primary signal)
#   W_GRAPH — weight for graph density signal (secondary structural signal)
# ---------------------------------------------------------------------------
W_VEC: float = 0.7
W_GRAPH: float = 0.3

# ---------------------------------------------------------------------------
# Graph signal normalisation
#   graph_signal = log(1 + entity_count) / LOG_NORM_BASE
#   Saturates at entity_count ≈ LOG_NORM_BASE - 1 (returns ≈ 1.0)
# ---------------------------------------------------------------------------
import math as _math

LOG_NORM_BASE: float = _math.log(10)  # saturates at ~9–10 entities

# ---------------------------------------------------------------------------
# Snippet length (chars) returned per result
# ---------------------------------------------------------------------------
SNIPPET_CHARS = 200
