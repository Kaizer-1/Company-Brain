# Why Graph Beats Pure RAG for Our 4 Killer Queries

This document explains why Retrieval-Augmented Generation (RAG) is the wrong primary architecture for Company Brain's core queries, and how the graph + vector hybrid we're building addresses the gaps. This is not an anti-RAG argument — RAG is in the stack. The argument is that *pure* RAG fails on structural reasoning, and structural reasoning is exactly what the 4 killer queries require.

## What RAG Does Well

Standard RAG: embed documents into a vector store → embed the query → retrieve nearest-k chunks → send chunks + query to an LLM → get an answer.

RAG is excellent at:
- **Open-ended summarisation**: "What is our database backup policy?" → retrieve relevant policy chunks → LLM summarises
- **Factual retrieval with semantic variation**: "Who is the on-call engineer?" when the document says "primary incident responder"
- **Question-answering within a document**: chunks from the same document are retrieved together, LLM reads and answers

RAG fails specifically at **structural reasoning** — queries that require following chains of typed relationships, comparing across time windows, or computing reachability. These are the 4 killer queries.

---

## Query 1: Multi-hop Ownership

> *Who owns the service that depends on the system deprecated by Decision X?*

**RAG attempt**: Embed the query, retrieve chunks mentioning Decision X and deprecated systems, retrieve chunks mentioning service dependencies and ownership. Send 4–6 chunks to an LLM and ask it to synthesise an answer.

**Why it fails**: The answer requires following a specific chain of 3 typed relationships:

```
Decision X → [DEPRECATED] → System Y → [DEPENDS_ON, reversed] → Service Z → [OWNS, reversed] → Person P
```

None of these relationships are stated in any single document chunk. The decision document says "we are deprecating System Y." A different document says "Service Z depends on System Y." A third document says "Person P owns Service Z." No individual document contains the full chain.

RAG retrieves chunks by *semantic proximity to the query*, not by *structural proximity in the relationship graph*. There is no guarantee that all three relevant chunks appear in the top-k — they may score lower than other chunks that mention "ownership" or "deprecation" in different contexts. And even if all three chunks are retrieved, the LLM must infer the chain from prose — it has no way to verify whether "Service Z depends on System Y" is still true today, or whether it was true when that document was written.

**Graph answer**: One Cypher MATCH clause. O(1) per hop. Guaranteed completeness — if the edge exists in the graph, the query finds it.

---

## Query 2: Temporal Contradiction

> *Which currently-active decisions are contradicted by discussions in the last month?*

**RAG attempt**: Retrieve decisions and recent messages by embedding similarity to the concept of "contradiction" or "disagreement." Send them to an LLM and ask it to identify conflicting pairs.

**Why it fails on three levels**:

1. **Contradiction is a structural relationship, not a semantic property**. Two documents can be semantically similar (both about the auth system) while being fully consistent. Two documents can be semantically distant while logically contradicting each other (one says "we will never store tokens in local storage"; a recent Slack message says "I hardcoded the token into localStorage for now, we can fix it later"). RAG retrieves nearest neighbours; it retrieves things *about* the same topic, not things that *contradict* each other.

2. **Temporal filtering is not native to RAG**. The query specifies "last month" and "currently active." Vector similarity has no temporal axis. To implement this in RAG, you'd add metadata filters (timestamp range) — but then you're doing post-retrieval filtering, which degrades recall (you've already fixed k before filtering). Graph-native temporal queries (`WHERE e.date > date() - duration('P30D')`) operate at the index level.

3. **Set comparison is not a retrieval problem**. Finding contradictions requires comparing the *set of active decisions* against the *set of recent discussions* — looking for logical opposites between two groups. RAG retrieves the top-k most similar chunks to a query; it finds similar things, not opposing things across groups.

**Graph answer**: In Phase 3B, the `CONTRADICTS` edge is a pre-computed relationship written when the contradiction is detected (by an LLM in Phase 2D). The query then becomes: traverse `CONTRADICTS` edges from currently-active decision nodes to their contradicting messages, filtered to the last 30 days. The LLM does the *extraction* once at write time; the graph serves the *query* at read time.

---

## Query 3: Blast Radius

> *If the payments service fails, which services, decisions, and people are affected?*

**RAG attempt**: Retrieve documents mentioning the payments service. Send to LLM: "what would break if payments failed?"

**Why it fails**: Blast radius requires **graph reachability** — find all nodes reachable via dependency and ownership edges from the payments service node. This is a graph algorithm (BFS or Cypher's variable-length path expansion).

The failure has two parts:

1. **Transitive dependencies are not documented**. Service A depends on Service B which depends on payments. Service A's documentation will mention its own dependencies, but it won't say "we also indirectly depend on payments via Service B." The transitive dependencies live in the topology of the graph, not in any document.

2. **Cross-entity blast radius is not a prose problem**. The query asks for affected *services* AND *decisions* AND *people*. A service depends on payments → a decision says "Service A must maintain 99.9% uptime" → the person who approved that decision is now accountable. Stitching these three entity types together requires knowing the graph topology, not reading documents about payments.

**Graph answer**: Variable-length path expansion in Cypher:
```cypher
MATCH (payments:Service {name: "payments-api"})<-[:DEPENDS_ON*1..5]-(affected:Service)
MATCH (affected)<-[:OWNS]-(owner:Person)
RETURN DISTINCT affected.name, owner.name
```
This returns every service within 5 dependency hops of payments and every person who owns any of those services — in one query.

---

## Query 4: Provenance + Change Tracking

> *What has changed about the auth system in the last quarter, and who approved each change?*

**RAG attempt**: Retrieve documents about the auth system from the last three months. Ask LLM to summarise changes and identify approvers.

**Why it fails**: This query requires reconstructing a **timeline of state transitions with attribution**.

1. **Changes are events, not documents**. A change to the auth system might be mentioned in: a decision record, a Slack message, a meeting note, a commit message. RAG retrieves chunks by similarity; it does not know that these chunks represent *events in a sequence*. The LLM receives an unordered set of relevant chunks and must infer temporal ordering from prose timestamps — which may be inconsistent, ambiguous, or absent.

2. **Approvals are relationships**. The approval of a change is a relationship between a change-event and a person: `(:Decision)-[:APPROVED_BY {timestamp: "..."}]->(:Person)`. This relationship is stored as a Slack reaction, a LGTM comment, or a signature in a document. RAG may retrieve the approval text, but it has no model of *who approved what* — it has text near the approval phrase, which may or may not identify the approver unambiguously.

3. **"Currently active" status requires graph state**. Knowing whether a decision is currently active requires following the `SUPERSEDED_BY` relationship chain. A decision may have been superseded by another decision which was itself superseded. Determining current active status requires traversing that chain — RAG retrieves text about the decision, but cannot reason about whether it has been superseded by a later decision that doesn't mention it by name.

**Graph answer**: Phase 3B writes `CHANGED` edges with timestamps as events are ingested; `APPROVED_BY` edges link each change to its approvers. The query is a time-filtered traversal over those edges with date-range constraints.

---

## The Hybrid Architecture

Company Brain is not anti-RAG. It uses both:

- **Graph**: structure, relationships, multi-hop traversal, temporal edge queries
- **pgvector + RAG**: semantic search within node content (e.g., "find messages *conceptually related to* the payments outage" where the match is semantic, not structural)

The agent layer in Phase 4A routes each query component to the right store. A query like "what has changed about the auth system" is decomposed into: (1) graph traversal for the change timeline and approvers, (2) vector search for related messages that discuss the auth system without explicit structure. The answer combines both: the graph provides the skeleton (what changed, who approved), the vector search provides the texture (what people were saying about it at the time).

Pure RAG handles component 2 but fails on component 1. Pure graph traversal handles component 1 but requires exact entity names for component 2. The hybrid handles both.
