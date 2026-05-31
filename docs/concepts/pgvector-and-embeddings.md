# pgvector and Embeddings

This document explains what embedding vectors are, how similarity search works, why we store embeddings in Postgres (co-location), and what the trade-offs are at larger scale.

## What Is an Embedding?

An **embedding** is a dense numeric vector — an array of floating-point numbers, typically 768 to 3072 dimensions — that encodes the semantic meaning of a piece of text. The key property is that texts with similar meaning produce vectors that are geometrically close to each other in the embedding space.

When an embedding model (e.g., OpenAI `text-embedding-3-small`, or a locally-hosted `nomic-embed-text`) processes the sentence:

> "The payments service is down, impacting checkout"

it outputs a vector like `[0.021, -0.147, 0.388, ..., 0.012]` (1536 floats for that model). The same model processing:

> "The payments API is experiencing an outage affecting the cart service"

outputs a *different* vector, but one that points in approximately the same direction in the 1536-dimensional space — because the two sentences mean the same thing.

This geometric encoding of meaning is what makes semantic search possible: instead of matching keywords, we measure direction in embedding space.

## Cosine Similarity

The standard similarity metric between two embedding vectors is **cosine similarity**:

```
similarity(A, B) = (A · B) / (|A| × |B|)
```

Where `A · B` is the dot product and `|A|`, `|B|` are the L2 norms (lengths) of the vectors.

- Cosine similarity of **1.0**: vectors point in the exact same direction → identical semantic meaning
- Cosine similarity of **0.0**: vectors are orthogonal → completely unrelated semantically
- Cosine similarity of **-1.0**: vectors point in opposite directions → semantically opposite

Because we care about direction (meaning) rather than magnitude (verbosity), cosine similarity outperforms L2 (Euclidean) distance for text embeddings. pgvector uses the `<=>` operator for cosine distance (= 1 - cosine similarity):

```sql
SELECT id, content
FROM messages
ORDER BY embedding <=> $1   -- $1 is the query embedding vector
LIMIT 10;
```

## What pgvector Is

`pgvector` is a Postgres extension that adds:

1. **`vector(n)` column type**: stores a fixed-width array of 32-bit floats as a Postgres column. `vector(1536)` stores an OpenAI `text-embedding-3-small` embedding; `vector(768)` stores a BERT-family embedding.

2. **Distance operators**:
   - `<=>` cosine distance
   - `<->` L2 (Euclidean) distance
   - `<#>` negative inner product (for models that use max inner product as similarity)

3. **Index types**:
   - **IVFFlat** (Inverted File Index): divides the vector space into `lists` Voronoi cells. Query probes `probes` cells. Fast to build, tunable recall. Good for development.
   - **HNSW** (Hierarchical Navigable Small World): builds a multi-layer graph where each layer is a subset of nodes connected to approximate nearest neighbours. Slower to build but faster and higher-recall at query time. Use HNSW for production.

## Why Co-location with Postgres Wins at Our Scale

The decisive argument for pgvector over Pinecone/Weaviate/Qdrant is **co-location with relational metadata**.

In Company Brain, an embedding is not useful in isolation. The interesting queries combine semantic similarity with relational filters:

```sql
-- "Find messages semantically similar to the auth outage, posted by the payments team in Q3 2025"
SELECT m.id, m.content, m.timestamp, p.name AS author
FROM messages m
JOIN persons p ON m.author_id = p.id
JOIN team_members tm ON p.id = tm.person_id
JOIN teams t ON tm.team_id = t.id
WHERE t.name = 'payments'
  AND m.timestamp BETWEEN '2025-07-01' AND '2025-09-30'
ORDER BY m.embedding <=> $1   -- semantic similarity
LIMIT 10;
```

This is one SQL query. With a dedicated vector database:
1. Query Pinecone/Qdrant for the top-k embedding IDs similar to `$1` → returns 100 candidate IDs
2. Query Postgres with `WHERE id IN (...)` to filter by team and date range → returns 10 results

The two-round-trip version has more latency (two network calls), more failure modes (two services), and the k-NN recall is degraded because you're filtering *after* the vector search rather than *during* it. With pgvector, Postgres plans the combined query and applies the vector index with the relational filters integrated.

This co-location advantage only exists because our embeddings live in the same database as their metadata. Moving to a dedicated vector DB sacrifices this for scale benefits that we don't need.

## Index Strategy for This Project

During development (Phase 1C–3C), we use no vector index — sequential scan is fast enough for <1000 rows.

In Phase 3D, we create an HNSW index:

```sql
CREATE INDEX ON messages USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

- `m = 16`: number of connections per node in each HNSW layer. Higher = better recall, slower build, more memory. 16 is the standard starting point.
- `ef_construction = 64`: candidates examined during index build per node. Higher = better recall in the final index.
- At query time, `SET hnsw.ef_search = 40` controls how many candidates are examined during search — tune upward to improve recall at the cost of speed.

## What Would Change at Larger Scale

pgvector with HNSW achieves >95% recall at <10ms for corpora up to ~5M vectors on a well-resourced Postgres instance. Beyond that:

| Scale | What changes |
|-------|-------------|
| ~5M vectors | HNSW index build time becomes slow (minutes); consider IVFFlat with higher `lists` |
| ~10M vectors | HNSW RAM footprint becomes significant (~20GB for 1536-dim vectors); dedicated store may be more memory-efficient |
| >1000 QPS vector search | Postgres read scaling (replica fan-out) can't match dedicated stores' horizontal sharding |
| Multi-tenancy | Per-tenant vector isolation in Postgres requires partition-per-tenant or tenant_id filtering; dedicated stores can provide stronger isolation |

At those thresholds, **Qdrant** (Rust, excellent resource efficiency, self-hosted) or **Weaviate** (if hybrid BM25+vector is the dominant query pattern) are the right replacements. The application layer in Phase 4A abstracts the vector store behind an interface, so the migration would be isolated to the embedding pipeline module.
