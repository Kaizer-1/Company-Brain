import { apiFetch } from './client';
import type { IngestEventRequest, IngestEventResponse } from '../types';

/**
 * Ingest a new event and reconcile it into the graph in real time (Phase 5A).
 *
 * Returns the full per-stage reconciliation result — the visible demo artifact the /ingest
 * page renders. A 200 with `deduplicated: true` means the event was already ingested (the
 * endpoint is idempotent on `external_id` / content). A 503 means another ingestion held the
 * single-writer lock past the timeout.
 */
export async function ingestEvent(body: IngestEventRequest): Promise<IngestEventResponse> {
  return apiFetch<IngestEventResponse>('/api/events', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}
