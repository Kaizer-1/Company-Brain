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

export type AgentRoute = 'kq1' | 'kq2' | 'kq3' | 'kq4' | 'search' | 'unknown';
export type AgentConfidence = 'high' | 'medium' | 'low';

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
  debug: AgentStateDump | null;
}
