import { apiFetch } from './client';
import type { AskResponse } from '../types';

/**
 * Ask the agent a natural-language question. Pass debug=true to receive the full agent
 * trace (route, reasoning, per-node timings) in the response for the "Show agent trace"
 * disclosure.
 */
export async function runAsk(question: string, debug = false): Promise<AskResponse> {
  return apiFetch<AskResponse>('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, debug }),
  });
}
