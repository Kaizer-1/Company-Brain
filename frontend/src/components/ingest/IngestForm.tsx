/**
 * The ingestion form: a large content textarea plus the event metadata fields. Submitting
 * posts to POST /api/events and the parent renders the reconciliation result.
 */

import { useState } from 'react';
import { Button } from '../ui/Button';
import type { IngestEventRequest, SourceKind } from '../../types';

interface IngestFormProps {
  onSubmit: (body: IngestEventRequest) => void;
  loading: boolean;
}

function nowLocalDatetime(): string {
  // `datetime-local` wants `YYYY-MM-DDTHH:mm` in local time.
  const d = new Date();
  const off = d.getTimezoneOffset();
  return new Date(d.getTime() - off * 60_000).toISOString().slice(0, 16);
}

const FIELD =
  'w-full bg-surface border border-border rounded px-3 py-2 text-sm text-txt ' +
  'placeholder:text-txt-faint focus-visible:outline-none focus-visible:ring-2 ' +
  'focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-bg';
const LABEL = 'block text-2xs font-mono uppercase tracking-wide text-txt-muted mb-1';

export function IngestForm({ onSubmit, loading }: IngestFormProps) {
  const [sourceKind, setSourceKind] = useState<SourceKind>('slack_message');
  const [sourceRef, setSourceRef] = useState('#payments-eng');
  const [occurredAt, setOccurredAt] = useState(nowLocalDatetime());
  const [externalId, setExternalId] = useState('');
  const [content, setContent] = useState('');

  const canSubmit = content.trim().length >= 10 && sourceRef.trim().length >= 1 && !loading;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    onSubmit({
      source_kind: sourceKind,
      source_ref: sourceRef.trim(),
      content: content.trim(),
      // datetime-local has no timezone; treat it as local and convert to ISO.
      occurred_at: new Date(occurredAt).toISOString(),
      external_id: externalId.trim() || null,
    });
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className={LABEL} htmlFor="ingest-content">
          Event content
        </label>
        <textarea
          id="ingest-content"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={5}
          placeholder="Paste a Slack message, doc snippet, or ADR section here…"
          className={`${FIELD} resize-y font-mono leading-relaxed`}
        />
        <p className="mt-1 text-2xs text-txt-faint">{content.trim().length} / 10000 chars</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className={LABEL} htmlFor="ingest-kind">Source kind</label>
          <select
            id="ingest-kind"
            value={sourceKind}
            onChange={(e) => setSourceKind(e.target.value as SourceKind)}
            className={FIELD}
          >
            <option value="slack_message">slack_message</option>
            <option value="doc">doc</option>
          </select>
        </div>
        <div>
          <label className={LABEL} htmlFor="ingest-ref">Source ref</label>
          <input
            id="ingest-ref"
            value={sourceRef}
            onChange={(e) => setSourceRef(e.target.value)}
            placeholder="#channel or doc title"
            className={FIELD}
          />
        </div>
        <div>
          <label className={LABEL} htmlFor="ingest-when">Occurred at</label>
          <input
            id="ingest-when"
            type="datetime-local"
            value={occurredAt}
            onChange={(e) => setOccurredAt(e.target.value)}
            className={FIELD}
          />
        </div>
        <div>
          <label className={LABEL} htmlFor="ingest-extid">
            External ID <span className="text-txt-faint normal-case">(optional, for idempotency)</span>
          </label>
          <input
            id="ingest-extid"
            value={externalId}
            onChange={(e) => setExternalId(e.target.value)}
            placeholder="auto-derived from content if blank"
            className={FIELD}
          />
        </div>
      </div>

      <Button type="submit" disabled={!canSubmit} loading={loading}>
        {loading ? 'Reconciling…' : 'Reconcile'}
      </Button>
    </form>
  );
}
