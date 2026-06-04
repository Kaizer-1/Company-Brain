import type { MergeDecisionPage } from '../types';
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
