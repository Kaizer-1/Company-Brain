/**
 * /ingest — live ingestion (Phase 5A). Paste an event, hit Reconcile, and watch the graph
 * reconcile it through the incremental pipeline in real time. The per-stage timeline and the
 * "what changed" panel below are the demo's climax: inject an event, then confirm the change
 * with the structural tools on /ask ("list all employees" → count + 1).
 *
 * Single-column layout, matching /ask.
 */

import { useState } from 'react';
import { ingestEvent } from '../api/ingest';
import { IngestForm } from '../components/ingest/IngestForm';
import { ReconciliationView } from '../components/ingest/ReconciliationView';
import { ApiError } from '../api/client';
import type { IngestEventRequest, IngestEventResponse } from '../types';

type Status = 'idle' | 'loading' | 'done' | 'error';

export function Ingest() {
  const [status, setStatus] = useState<Status>('idle');
  const [result, setResult] = useState<IngestEventResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(body: IngestEventRequest) {
    setStatus('loading');
    setError(null);
    try {
      const response = await ingestEvent(body);
      setResult(response);
      setStatus('done');
    } catch (e) {
      const detail =
        e instanceof ApiError
          ? e.status === 503
            ? 'Ingestion is busy — another reconciliation is in progress. Try again in a moment.'
            : e.detail
          : 'Unexpected error during ingestion.';
      setError(detail);
      setStatus('error');
    }
  }

  return (
    <div className="mx-auto max-w-[720px] px-5 py-8 space-y-8">
      <header className="space-y-1">
        <h1 className="text-lg font-medium text-txt">Ingest an event</h1>
        <p className="text-sm text-txt-muted">
          Add a Slack message, doc, or ADR snippet and watch it reconcile into the graph live —
          extraction, resolution, temporal enrichment, and contradiction detection, scoped to this
          one event.
        </p>
      </header>

      <IngestForm onSubmit={handleSubmit} loading={status === 'loading'} />

      {status === 'error' && error && (
        <div
          role="alert"
          className="rounded border border-red-800/40 bg-red-950/30 px-4 py-3 text-sm text-red-300"
        >
          {error}
        </div>
      )}

      {status === 'loading' && (
        <div className="rounded border border-border bg-s2 px-4 py-3 text-sm text-txt-muted">
          Reconciling… running the incremental pipeline (this can take a few seconds — two LLM
          calls are in the critical path).
        </div>
      )}

      {status === 'done' && result && <ReconciliationView result={result} />}
    </div>
  );
}
