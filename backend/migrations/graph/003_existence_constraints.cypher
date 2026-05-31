// 003_existence_constraints.cypher
//
// Property-existence (NOT NULL) constraints for each node label's mandatory
// fields. These would enforce, at the database, that e.g. a :Decision always
// has a valid_from and status.
//
// ---------------------------------------------------------------------------
// DELIBERATELY EMPTY ON NEO4J COMMUNITY 5.x.
// ---------------------------------------------------------------------------
// Property-existence constraints (REQUIRE n.prop IS NOT NULL) are a Neo4j
// ENTERPRISE feature. They do not exist in Community Edition 5.x, which this
// project targets (ADR 0002). Executing the statements below on Community
// raises an error, so they are left commented out. The file is still tracked
// and recorded by the migration runner as a no-op, so the migration ledger is
// complete and ordering is preserved if we later move to Enterprise.
//
// Until then, required-field enforcement happens at the APPLICATION boundary:
// the Pydantic models in backend/app/schemas/graph.py declare these fields as
// required (no default) with model_config extra="forbid", so no node can be
// constructed in Python without them. The graph and the application agree on
// the contract; only the enforcement point differs.
//
// To enable on Neo4j Enterprise, uncomment:
//
// CREATE CONSTRAINT service_canonical_name_exists IF NOT EXISTS
// FOR (s:Service) REQUIRE s.canonical_name IS NOT NULL;
//
// CREATE CONSTRAINT system_canonical_name_exists IF NOT EXISTS
// FOR (s:System) REQUIRE s.canonical_name IS NOT NULL;
//
// CREATE CONSTRAINT team_canonical_name_exists IF NOT EXISTS
// FOR (t:Team) REQUIRE t.canonical_name IS NOT NULL;
//
// CREATE CONSTRAINT person_canonical_id_exists IF NOT EXISTS
// FOR (p:Person) REQUIRE p.canonical_id IS NOT NULL;
//
// CREATE CONSTRAINT decision_id_exists IF NOT EXISTS
// FOR (d:Decision) REQUIRE d.id IS NOT NULL;
//
// CREATE CONSTRAINT decision_valid_from_exists IF NOT EXISTS
// FOR (d:Decision) REQUIRE d.valid_from IS NOT NULL;
//
// CREATE CONSTRAINT decision_status_exists IF NOT EXISTS
// FOR (d:Decision) REQUIRE d.status IS NOT NULL;
//
// CREATE CONSTRAINT message_id_exists IF NOT EXISTS
// FOR (m:Message) REQUIRE m.id IS NOT NULL;
//
// CREATE CONSTRAINT message_created_at_exists IF NOT EXISTS
// FOR (m:Message) REQUIRE m.created_at IS NOT NULL;
