import { apiFetch } from './client';
import type { SearchRequest, SearchResult } from '../types';

export async function runSearch(req: SearchRequest): Promise<SearchResult> {
  return apiFetch<SearchResult>('/api/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
}
