// 002_indexes.cypher
// Secondary indexes that make the killer queries fast. Each is a RANGE index
// (Neo4j 5.x default for CREATE INDEX), which serves both equality and range
// predicates. See docs/design/graph-schema.md ("The Four Killer Queries as
// Cypher") for which query each index serves.
//
// Idempotent via CREATE INDEX ... IF NOT EXISTS.
//
// NOTE: we deliberately do NOT index canonical_name / canonical_id / id here.
// Those properties already carry a uniqueness constraint (001_constraints.cypher),
// and a uniqueness constraint creates its own backing index. Adding a second
// index on the same property would be redundant.

// KQ2: filter Decision by status = 'active'.
CREATE INDEX decision_status_index IF NOT EXISTS
FOR (d:Decision) ON (d.status);

// KQ4: filter Decision by valid_from >= (now - 1 quarter). Range predicate.
CREATE INDEX decision_valid_from_index IF NOT EXISTS
FOR (d:Decision) ON (d.valid_from);

// KQ2: filter Message by created_at >= (now - 1 month). Range predicate.
CREATE INDEX message_created_at_index IF NOT EXISTS
FOR (m:Message) ON (m.created_at);
