/**
 * Shared TypeScript types mirroring the backend's Pydantic response shapes.
 * These are the DTOs that cross the API boundary into the frontend.
 */

// ── Graph ────────────────────────────────────────────────────────────────────

export interface GraphNode {
  id: string;              // Neo4j elementId — unique per session
  node_type: NodeType;
  label: string;           // human-readable display name
  status: NodeStatus;
  source_event_ids: string[];
  canonical_id: string | null;
}

export interface GraphEdge {
  id: string;
  source: string;          // source node elementId
  target: string;          // target node elementId
  edge_type: string;
  is_merge_into: boolean;
  confidence: number | null;
  source_event_id: string | null;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  view: 'resolved' | 'fragmented';
}

export type NodeType = 'Decision' | 'Service' | 'System' | 'Person' | 'Team' | 'Message';
export type NodeStatus = 'active' | 'merged' | 'superseded';

// ── Queries ──────────────────────────────────────────────────────────────────

export interface QueryProvenance {
  by_element: Record<string, string[]>;
  all_event_ids?: string[];   // computed_field — absent in old backend responses
}

export interface QueryResult<T> {
  value: T;
  provenance: QueryProvenance;
}

// KQ1
export interface OwnershipChain {
  deprecated_system: string;
  dependent_service: string;
  owner_type: string;
  owner_id: string;
  person_id: string | null;
  person_display_name: string | null;
  nodes: string[];
}

export interface ChainOwnerAnswer {
  decision_id: string;
  decision_title: string | null;
  deprecated_systems: string[];
  owner_people: string[];
  chains: OwnershipChain[];
}

// KQ2 — matches backend ContradictingMessage + Contradiction models
export interface ContradictingMessage {
  message_id: string;
  said_at: string | null;
  confidence: number | null;
}

export interface Contradiction {
  decision_id: string;
  decision_title: string | null;
  messages: ContradictingMessage[];
}

// KQ3 — matches backend BlastRadius model (affected_* prefix)
export interface BlastRadius {
  seed_service: string;
  affected_services: string[];
  affected_people: string[];
  affected_decisions: string[];
  max_depth_reached: number;
}

// KQ4 — matches backend DecisionChange + ChangeTimeline models
export interface DecisionChange {
  decision_id: string;
  title: string | null;
  status: string | null;
  valid_from: string | null;
  approvers: string[];
  supersedes: string[];
}

export interface ChangeTimeline {
  target: string;
  changes: DecisionChange[];
}

// ── Audit ────────────────────────────────────────────────────────────────────

export type DecisionType =
  | 'auto_merge'
  | 'llm_merge'
  | 'llm_no_merge'
  | 'below_threshold'
  | 'content_merge';

export interface MergeDecisionDTO {
  id: string;
  source_node_id: string;
  target_node_id: string;
  node_type: string;
  decision: DecisionType;
  tier: number;
  embedding_similarity: number | null;
  rules_matched: string[];
  llm_reasoning: string | null;
  llm_model: string | null;
  created_at: string;
}

export interface MergeDecisionPage {
  items: MergeDecisionDTO[];
  total: number;
  limit: number;
  offset: number;
}

// ── Search ───────────────────────────────────────────────────────────────────

export interface SearchFilters {
  source_kind?: string[] | null;
  after?: string | null;
  before?: string | null;
  entity_type?: string[] | null;
}

export interface SearchRequest {
  query: string;
  k?: number;
  filters?: SearchFilters | null;
}

export interface SearchHit {
  event_id: string;
  snippet: string;
  source_kind: string;
  source_ref: string;
  occurred_at: string;
  similarity_score: number;
  final_score: number;
  related_entity_ids: string[];
}

export interface SearchResult {
  query: string;
  hits: SearchHit[];
  total_candidates: number;
  query_embedding_ms: number;
  vector_search_ms: number;
  rerank_ms: number;
  total_ms: number;
}

// ── Events ───────────────────────────────────────────────────────────────────

export interface EventDTO {
  id: string;
  source_type: 'doc' | 'slack_message';
  source_external_id: string;
  content: string;
  source_metadata: Record<string, unknown>;
  created_at: string;
  ingested_at: string;
  content_hash: string;
}

// ── Agent (/ask) ──────────────────────────────────────────────────────────────

export type AgentRoute =
  | 'kq1'
  | 'kq2'
  | 'kq3'
  | 'kq4'
  | 'search'
  | 'get_entity'
  | 'neighbors'
  | 'enumerate'
  | 'aggregate'
  | 'unknown';
export type AgentConfidence = 'high' | 'medium' | 'low';

// ── Structural tool results (Phase 4C) ─────────────────────────────────────────
// The backend carries the raw structural tool output as `tool_output` on AskResponse /
// the `complete` stream event. It is a QueryResult envelope: { value, provenance }.

export interface EntityResult {
  entity_id: string;
  node_type: string; // matched label, or "not_found"
  properties: Record<string, unknown>;
  outgoing_edges: Record<string, number>;
  incoming_edges: Record<string, number>;
  source_event_ids: string[];
}

export interface NeighborItem {
  neighbor_id: string;
  neighbor_name: string;
  neighbor_type: string;
  edge_type: string;
  outgoing: boolean;
  source_event_id: string | null;
}

export interface NeighborsResult {
  entity_id: string;
  total_count: number;
  neighbors: NeighborItem[];
}

export interface EnumeratedNode {
  id: string;
  name: string;
  status: string;
  extra_fields: Record<string, unknown>;
  source_event_ids: string[];
}

export interface EnumerateResult {
  node_type: string;
  total_count: number;
  returned_count: number;
  nodes: EnumeratedNode[];
  filters_applied: Record<string, unknown>;
}

export interface AggregateGroup {
  group_name: string;
  group_type: string;
  count: number;
}

export interface AggregateResult {
  node_type: string;
  total: number;
  groups: AggregateGroup[] | null;
}

export type StructuralResult =
  | EntityResult
  | NeighborsResult
  | EnumerateResult
  | AggregateResult;

// The QueryResult envelope the backend serialises into tool_output.
export interface ToolOutput {
  value: StructuralResult;
  provenance?: QueryProvenance;
}

export interface AskRequest {
  question: string;
  debug?: boolean;
}

export interface Citation {
  event_id: string;
  source_kind: string;
  source_ref: string;
  snippet: string;
}

export interface AgentStateDump {
  question: string;
  route: AgentRoute;
  route_reasoning: string;
  tool_input: Record<string, unknown>;
  available_event_ids: string[];
  answer: string;
  citations: string[];
  verified: boolean;
  retry_count: number;
  error: string | null;
  timings_ms: Record<string, number>;
  cost_usd: number;
}

export interface AskResponse {
  answer: string;
  citations: Citation[];
  route: AgentRoute;
  confidence: AgentConfidence;
  timings_ms: Record<string, number>;
  error: string | null;
  tool_output?: ToolOutput | null; // structural routes only (Phase 4C)
  debug: AgentStateDump | null;
}

// ── Streaming (/ask/stream) ───────────────────────────────────────────────────

export type StreamEventType =
  | 'route'
  | 'tool_start'
  | 'tool_done'
  | 'synthesis_start'
  | 'synthesis_token'
  | 'synthesis_done'
  | 'verify_start'
  | 'verify_done'
  | 'complete'
  | 'error';

export interface StreamEventRoute {
  type: 'route';
  route: AgentRoute;
  reasoning: string;
  tool_input: Record<string, unknown>;
}

export interface StreamEventToolStart {
  type: 'tool_start';
  tool: string;
  params: Record<string, unknown>;
}

export interface StreamEventToolDone {
  type: 'tool_done';
  tool_output_summary: string;
  timings_ms: Record<string, number>;
}

export interface StreamEventSynthesisStart {
  type: 'synthesis_start';
  retry: boolean;
}

export interface StreamEventSynthesisToken {
  type: 'synthesis_token';
  text: string;
}

export interface StreamEventSynthesisDone {
  type: 'synthesis_done';
  answer_final: string;
  citations_raw: string[];
}

export interface StreamEventVerifyStart {
  type: 'verify_start';
}

export interface StreamEventVerifyDone {
  type: 'verify_done';
  verified: boolean;
  retry_count: number;
}

export interface StreamEventComplete {
  type: 'complete';
  answer: string;
  citations: Citation[];
  route: AgentRoute;
  confidence: AgentConfidence;
  timings_ms: Record<string, number>;
  error: string | null;
  tool_output?: ToolOutput | null; // structural routes only (Phase 4C)
  debug: AgentStateDump | null;
}

export interface StreamEventError {
  type: 'error';
  error: string;
  stage: string;
}

export type StreamEvent =
  | StreamEventRoute
  | StreamEventToolStart
  | StreamEventToolDone
  | StreamEventSynthesisStart
  | StreamEventSynthesisToken
  | StreamEventSynthesisDone
  | StreamEventVerifyStart
  | StreamEventVerifyDone
  | StreamEventComplete
  | StreamEventError;

// ─────────────────────────────────────────────────────────────────────────────
// Live ingestion (Phase 5A) — POST /api/events
// ─────────────────────────────────────────────────────────────────────────────
export type SourceKind = 'doc' | 'slack_message';
export type IngestionStatus = 'reconciled' | 'partial' | 'failed';
export type StageStatus = 'ok' | 'skipped' | 'failed';

export interface IngestEventRequest {
  source_kind: SourceKind;
  source_ref: string;
  content: string;
  occurred_at: string; // ISO-8601
  external_id?: string | null;
}

export interface StageResult {
  name: string;
  status: StageStatus;
  duration_ms: number;
  detail: string | null;
}

export interface NodeRef {
  id: string;
  label: string;
  display_name: string;
}

export interface MergeRef {
  loser_id: string;
  winner_id: string;
  label: string;
  tier: number;
  confidence: number;
}

export interface EdgeRef {
  type: string;
  source_id: string;
  target_id: string;
}

export interface ContradictionRef {
  message_id: string;
  decision_id: string;
  confidence: number;
}

export interface IngestEventResponse {
  event_id: string;
  status: IngestionStatus;
  stages_run: StageResult[];
  nodes_created: NodeRef[];
  nodes_merged: MergeRef[];
  edges_created: EdgeRef[];
  contradictions_detected: ContradictionRef[];
  duration_ms: number;
  cost_usd: number;
  deduplicated: boolean;
}

// ─────────────────────────────────────────────────────────────────────────────
// Observability (Phase 5B) — GET /api/audit/ingestion-runs + GET /api/metrics
// ─────────────────────────────────────────────────────────────────────────────

// One ingestion run joined to its source event, for the /audit "Ingestion runs" tab.
export interface IngestionRunSummary {
  id: string;
  event_id: string;
  source_kind: SourceKind;
  content_snippet: string;
  status: IngestionStatus;
  stages: StageResult[];
  nodes_created_count: number;
  nodes_merged_count: number;
  edges_created_count: number;
  contradictions_count: number;
  cost_usd: number;
  duration_ms: number | null;
  started_at: string;
  completed_at: string | null;
  error: string | null;
}

export interface IngestionRunPage {
  items: IngestionRunSummary[];
  next_cursor: string | null; // started_at cursor for the next page; null = no more rows
}

// System metrics snapshot (mirrors backend MetricsSnapshot).
export interface DurationStats {
  p50: number;
  p95: number;
  max: number;
}

export interface CostStats {
  mean: number;
  p95: number;
  total: number;
}

export interface SystemMetrics {
  ingestion: {
    total: number;
    by_status: Record<string, number>;
    duration_ms: DurationStats;
    cost_usd: CostStats;
  };
  stages: Record<string, { count: number; duration_ms: DurationStats }>;
  adjudications: {
    resolution_total: number;
    resolution_by_tier: Record<string, number>;
    contradiction_total: number;
  };
}
