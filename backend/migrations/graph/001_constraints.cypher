// 001_constraints.cypher
// Uniqueness constraints on each node label's canonical identifier.
// See docs/design/graph-schema.md ("Uniqueness and Identity") for the rationale.
//
// Every statement uses CREATE CONSTRAINT ... IF NOT EXISTS so the file is
// idempotent: re-running it never errors. A uniqueness constraint also creates
// a backing range index, so the killer queries that seed on these properties
// (e.g. Service.canonical_name) are index-served without a separate index.
// Constraints are split one-per-statement, terminated by ';', so the Python
// runner (backend/app/db/migrations.py) can execute them individually.

CREATE CONSTRAINT service_canonical_name_unique IF NOT EXISTS
FOR (s:Service) REQUIRE s.canonical_name IS UNIQUE;

CREATE CONSTRAINT system_canonical_name_unique IF NOT EXISTS
FOR (s:System) REQUIRE s.canonical_name IS UNIQUE;

CREATE CONSTRAINT team_canonical_name_unique IF NOT EXISTS
FOR (t:Team) REQUIRE t.canonical_name IS UNIQUE;

CREATE CONSTRAINT person_canonical_id_unique IF NOT EXISTS
FOR (p:Person) REQUIRE p.canonical_id IS UNIQUE;

CREATE CONSTRAINT decision_id_unique IF NOT EXISTS
FOR (d:Decision) REQUIRE d.id IS UNIQUE;

CREATE CONSTRAINT message_id_unique IF NOT EXISTS
FOR (m:Message) REQUIRE m.id IS UNIQUE;

// Bookkeeping node used by the migration runner to track applied migrations.
CREATE CONSTRAINT migration_name_unique IF NOT EXISTS
FOR (mig:_Migration) REQUIRE mig.name IS UNIQUE;
