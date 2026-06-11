import type { IngestionRunPage, MergeDecisionPage, SystemMetrics } from '../types';
import { apiFetch } from './client';

export interface AuditFilters {
  tier?: number | null;
  decision?: string | null;
  node_type?: string | null;
  limit?: number;
  offset?: number;
}

export function fetchAudit(filters: AuditFilters = {}): Promise<MergeDecisionPage> {
  const params = new URLSearchParams();
  if (filters.tier != null) params.set('tier', String(filters.tier));
  if (filters.decision) params.set('decision', filters.decision);
  if (filters.node_type) params.set('node_type', filters.node_type);
  params.set('limit', String(filters.limit ?? 50));
  params.set('offset', String(filters.offset ?? 0));
  return apiFetch<MergeDecisionPage>(`/api/audit/merge-decisions?${params.toString()}`);
}

// ── Phase 5B: ingestion-runs audit feed + system metrics ──────────────────────

export interface IngestionRunsParams {
  limit?: number;
  before?: string | null; // cursor = a prior page's next_cursor (started_at)
}

export function fetchIngestionRuns(
  params: IngestionRunsParams = {},
): Promise<IngestionRunPage> {
  const q = new URLSearchParams();
  q.set('limit', String(params.limit ?? 20));
  if (params.before) q.set('before', params.before);
  return apiFetch<IngestionRunPage>(`/api/audit/ingestion-runs?${q.toString()}`);
}

export function fetchSystemMetrics(): Promise<SystemMetrics> {
  return apiFetch<SystemMetrics>('/api/metrics');
}
