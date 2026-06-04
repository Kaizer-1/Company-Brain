import type { GraphResponse } from '../types';
import { apiFetch } from './client';

export function fetchGraph(view: 'resolved' | 'fragmented'): Promise<GraphResponse> {
  return apiFetch<GraphResponse>(`/api/graph?view=${view}`);
}
