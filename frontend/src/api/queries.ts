import type {
  BlastRadius,
  ChainOwnerAnswer,
  ChangeTimeline,
  Contradiction,
  QueryResult,
} from '../types';
import { apiFetch } from './client';

export function fetchKq1(decisionId: string): Promise<QueryResult<ChainOwnerAnswer>> {
  return apiFetch<QueryResult<ChainOwnerAnswer>>(
    `/api/queries/multihop-ownership?decision_id=${encodeURIComponent(decisionId)}`,
  );
}

export function fetchKq2(windowDays: number): Promise<QueryResult<Contradiction[]>> {
  return apiFetch<QueryResult<Contradiction[]>>(
    `/api/queries/contradictions?window_days=${windowDays}`,
  );
}

export function fetchKq3(service: string, maxDepth: number): Promise<QueryResult<BlastRadius>> {
  return apiFetch<QueryResult<BlastRadius>>(
    `/api/queries/blast-radius?service=${encodeURIComponent(service)}&max_depth=${maxDepth}`,
  );
}

export function fetchKq4(target: string, windowDays: number): Promise<QueryResult<ChangeTimeline>> {
  return apiFetch<QueryResult<ChangeTimeline>>(
    `/api/queries/change-tracking?target=${encodeURIComponent(target)}&window_days=${windowDays}`,
  );
}
