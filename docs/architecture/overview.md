# Architecture Overview

## System Summary

Company Brain is a knowledge graph pipeline with three functional layers: **ingestion** (parse and extract entities from raw text), **storage** (graph + vector + relational), and **query** (agent-driven traversal and retrieval). The system is designed around four killer queries that require graph traversal — queries that pure RAG cannot answer reliably.

## Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         Company Brain                           │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │  Ingestion   │    │   Storage    │    │   Query Agent    │  │
│  │  Pipeline    │    │   Layer      │    │   (Phase 4A)     │  │
│  │              │    │              │    │                  │  │
│  │ • Raw text   │    │ ┌──────────┐ │    │ • Query router   │  │
│  │ • Slack msgs │───▶│ │  Neo4j   │ │◀───│ • Graph Cypher   │  │
│  │ • Decisions  │    │ │  5.x     │ │    │ • Vector search  │  │
│  │ • Meetings   │    │ │  (graph) │ │    │ • LLM synthesis  │  │
│  │              │    │ └──────────┘ │    │ • Provenance     │  │
│  │ • Parser     │    │              │    └──────────────────┘  │
│  │ • LLM extrac.│    │ ┌──────────┐ │             │            │
│  │ • Dedup      │    │ │Postgres  │ │             │            │
│  └──────────────┘    │ │16 +      │ │    ┌────────▼─────────┐  │
│                      │ │pgvector  │ │    │   FastAPI        │  │
│                      │ │(rel+vec) │ │    │   REST API       │  │
│                      │ └──────────┘ │    │   GET /health    │  │
│                      └──────────────┘    │   POST /query    │  │
│                                          │   (Phase 3+)     │  │
└──────────────────────────────────────────┴──────────────────┘

                                          ┌──────────────────┐
                                          │   Frontend       │
                                          │   (Phase 4B)     │
                                          │   react-force-   │
                                          │   graph          │
                                          └──────────────────┘
```

## Data Flow

### Write path (ingestion → graph)

```
Raw text (Slack/doc)
    │
    ▼
Parser (Phase 2B/2C)
    │  normalised message/document
    ▼
LLM Entity Extractor (Phase 2D)
    │  {entities: [Service, Person, ...], relationships: [DEPENDS_ON, ...]}
    ▼
Graph Writer (Phase 2E)
    ├──▶ Neo4j: MERGE nodes + relationships (upsert by canonical ID)
    └──▶ Postgres: INSERT metadata rows + embedding vectors
```

### Read path (query → answer)

```
Natural language question
    │
    ▼
Query Router (Phase 4A)
    ├── structural query → Cypher traversal (Neo4j)
    └── semantic query  → vector search (Postgres/pgvector)
         │
         ▼
    Results merged
         │
         ▼
    LLM synthesis with provenance
         │
         ▼
    Answer + source citations
```

## Storage Design

### Neo4j (graph layer)

Stores **structure**: who owns what, what depends on what, what supersedes what, what contradicts what. Every fact that can be expressed as a typed edge between two entities lives here. Optimised for:
- Variable-length path traversal (blast radius)
- Pattern matching (ownership chain)
- Temporal edge queries (contradiction detection)

### Postgres + pgvector (relational + vector layer)

Stores **content and metadata**: the full text of messages and decisions, timestamps, author IDs, team IDs — the relational data. Also stores **embedding vectors** for semantic search. Designed for:
- Relational filters (by team, date range, service)
- Semantic similarity search with `<=>` cosine distance
- Combined relational + vector queries in a single SQL statement

The two databases are complementary, not redundant. A query like "find all people affected by a blast radius scenario who have written about this topic in the last month" needs *both*: the blast radius requires Neo4j graph traversal; the "written about this topic" requires pgvector semantic search. The agent layer joins the results.

## Phase 1A State

In the current phase (1A), only the foundation is present:

- **Neo4j**: running in Docker, APOC plugin enabled, no schema defined
- **Postgres**: running in Docker with pgvector extension installed, no tables defined
- **FastAPI**: one endpoint (`GET /health`) that probes both DBs
- **Tests**: three tests for the health endpoint, fully mocked
- **Frontend**: placeholder directory only

All business logic, schema, ingestion, and query capability will be added in Phases 1B–4B.

## Key Constraints

| Constraint | Implication |
|------------|-------------|
| Synthetic data only | No real Slack, no real decision records; all data generated in Phase 2A |
| Closed entity types | Schema is fixed; no runtime schema evolution |
| Single tenant | No `org_id` isolation; all data in one graph |
| Demo scale (~10k nodes) | No horizontal scaling, no read replicas |
| No production auth | API is open on the Docker network; no JWT/OAuth |

These constraints are deliberate and named. See `README.md` → "Limitations and Future Work" for the full list with remediation notes.
