/**
 * IngestionRunsTab — the /audit "Ingestion runs" tab (Phase 5B, Decision 1).
 *
 * Mirrors the resolution-decisions table's shape, one row per live reconciliation the engine
 * performed: status, the source event (clickable → EventModal), a per-stage status mini-timeline,
 * the node/edge/contradiction counts, cost, and duration. Newest first, cursor-paginated with a
 * "Load more" button. The compact System metrics strip renders at the bottom.
 */

import { useInfiniteQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { fetchIngestionRuns } from '../../api/audit';
import { Badge } from '../ui/Badge';
import { ProgressBar } from '../ui/ProgressBar';
import { ErrorMessage } from '../ui/ErrorMessage';
import { Skeleton } from '../ui/Skeleton';
import { EventModal } from '../graph/EventModal';
import { SystemMetrics } from './SystemMetrics';
import type { IngestionRunSummary, StageResult, StageStatus } from '../../types';

const PAGE_SIZE = 20;

const STATUS_STYLES: Record<string, { label: string; className: string }> = {
  reconciled: { label: 'reconciled', className: 'bg-emerald-950/50 text-emerald-400 border-emerald-800/40' },
  partial: { label: 'partial', className: 'bg-amber-950/50 text-amber-400 border-amber-800/40' },
  failed: { label: 'failed', className: 'bg-red-950/50 text-red-400 border-red-800/40' },
};

const STAGE_DOT: Record<StageStatus, string> = {
  ok: 'bg-emerald-500',
  skipped: 'bg-zinc-600',
  failed: 'bg-red-500',
};

function formatDuration(ms: number | null): string {
  if (ms == null) return '—';
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

export function IngestionRunsTab() {
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);

  const { data, isLoading, error, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteQuery({
      queryKey: ['ingestion-runs'],
      queryFn: ({ pageParam }) => fetchIngestionRuns({ before: pageParam, limit: PAGE_SIZE }),
      initialPageParam: null as string | null,
      getNextPageParam: (last) => last.next_cursor,
      staleTime: 30_000,
    });

  const rows = data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="space-y-4">
      <ProgressBar visible={isLoading} />

      <div>
        <h1 className="text-xl font-semibold text-txt">Ingestion runs</h1>
        <p className="text-sm text-txt-muted mt-1">
          Every live reconciliation the engine performed — its per-stage timeline, what changed,
          cost, and latency. One row per ingested event, newest first.
        </p>
      </div>

      {error && (
        <ErrorMessage error={error instanceof Error ? error : new Error(String(error))} />
      )}

      {isLoading && !data ? (
        <TableSkeleton />
      ) : (
        <>
          <RunsTable rows={rows} onSelectEvent={setSelectedEventId} />

          {hasNextPage && (
            <div className="flex justify-center pt-1">
              <button
                onClick={() => void fetchNextPage()}
                disabled={isFetchingNextPage}
                className="text-xs text-accent hover:text-accent-hover disabled:text-txt-faint cursor-pointer disabled:cursor-not-allowed transition-colors"
              >
                {isFetchingNextPage ? 'Loading…' : 'Load more'}
              </button>
            </div>
          )}
        </>
      )}

      <SystemMetrics />

      {selectedEventId && (
        <EventModal eventId={selectedEventId} onClose={() => setSelectedEventId(null)} />
      )}
    </div>
  );
}

// ── Table ─────────────────────────────────────────────────────────────────────

function RunsTable({
  rows,
  onSelectEvent,
}: {
  rows: IngestionRunSummary[];
  onSelectEvent: (eventId: string) => void;
}) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-txt-muted py-6 text-center">
        No ingestion runs yet. Ingest an event on the <span className="text-txt">/ingest</span> page
        to see it here.
      </p>
    );
  }

  return (
    <div className="border border-border rounded overflow-hidden">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border bg-s2 text-left">
            <Th>Status</Th>
            <Th>Event</Th>
            <Th>Stages</Th>
            <Th>Nodes (new/merged)</Th>
            <Th>Edges</Th>
            <Th>Contradictions</Th>
            <Th>Cost</Th>
            <Th>Duration</Th>
            <Th>Created</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <RunRow key={row.id} row={row} onSelectEvent={onSelectEvent} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RunRow({
  row,
  onSelectEvent,
}: {
  row: IngestionRunSummary;
  onSelectEvent: (eventId: string) => void;
}) {
  const status = STATUS_STYLES[row.status] ?? {
    label: row.status,
    className: 'bg-s2 text-txt-muted border-border',
  };

  return (
    <tr className="border-b border-border hover:bg-s2 transition-colors align-top">
      <Td>
        <Badge variant="default" className={status.className}>
          {status.label}
        </Badge>
      </Td>
      <Td>
        <button
          onClick={() => onSelectEvent(row.event_id)}
          title={`${row.event_id}\n${row.content_snippet}`}
          className="text-left cursor-pointer group"
        >
          <span className="font-mono text-accent group-hover:text-accent-hover transition-colors">
            {row.event_id.slice(0, 8)}
          </span>
          <span className="block text-txt-faint max-w-[200px] truncate">
            {row.source_kind} · {row.content_snippet}
          </span>
        </button>
      </Td>
      <Td>
        <StageTimeline stages={row.stages} />
      </Td>
      <Td>
        <span className="font-mono text-txt">
          {row.nodes_created_count}
          <span className="text-txt-faint"> / </span>
          {row.nodes_merged_count}
        </span>
      </Td>
      <Td>
        <span className="font-mono text-txt-muted">{row.edges_created_count}</span>
      </Td>
      <Td>
        <span className="font-mono text-txt-muted">{row.contradictions_count}</span>
      </Td>
      <Td>
        <span className="font-mono text-txt-muted">${row.cost_usd.toFixed(3)}</span>
      </Td>
      <Td>
        <span className="font-mono text-txt">{formatDuration(row.duration_ms)}</span>
      </Td>
      <Td>
        <span className="font-mono text-txt-muted whitespace-nowrap">
          {new Date(row.started_at).toLocaleDateString()}{' '}
          {new Date(row.started_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </span>
      </Td>
    </tr>
  );
}

function StageTimeline({ stages }: { stages: StageResult[] }) {
  return (
    <div className="flex items-center gap-1">
      {stages.map((s, i) => (
        <span
          key={`${s.name}-${i}`}
          title={`${s.name}: ${s.status} (${Math.round(s.duration_ms)}ms)`}
          className={`h-2 w-2 rounded-full ${STAGE_DOT[s.status] ?? 'bg-zinc-600'}`}
        />
      ))}
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-3 py-2.5 font-medium text-txt-muted whitespace-nowrap text-2xs uppercase tracking-widest">
      {children}
    </th>
  );
}

function Td({ children }: { children: React.ReactNode }) {
  return <td className="px-3 py-2.5 align-top">{children}</td>;
}

function TableSkeleton() {
  return (
    <div className="border border-border rounded overflow-hidden">
      <div className="bg-s2 h-10 border-b border-border" />
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="px-3 py-2.5 border-b border-border">
          <Skeleton className="h-4 w-full" />
        </div>
      ))}
    </div>
  );
}
