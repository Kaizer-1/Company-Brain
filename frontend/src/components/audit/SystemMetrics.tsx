/**
 * SystemMetrics — the compact "System metrics" strip at the bottom of the Ingestion runs tab
 * (Phase 5B, Decision 2). Reads GET /api/metrics and shows a handful of numbers — total
 * ingestions, median + p95 latency, mean cost — plus the resolution-adjudication counts that
 * motivate the parallel-resolution work. Deliberately prose-compact, NOT a dashboard.
 *
 * The numbers are process-local and reset when the backend restarts; that caveat is shown
 * inline so the demo audience isn't misled into thinking it's a persistent time series.
 */

import { useQuery } from '@tanstack/react-query';
import { fetchSystemMetrics } from '../../api/audit';

function formatLatency(ms: number): string {
  if (ms <= 0) return '—';
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="min-w-[7rem]">
      <p className="text-2xs uppercase tracking-widest text-txt-muted">{label}</p>
      <p className="font-mono text-lg text-txt mt-0.5">{value}</p>
      {hint && <p className="text-2xs text-txt-faint mt-0.5">{hint}</p>}
    </div>
  );
}

export function SystemMetrics() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['metrics'],
    queryFn: fetchSystemMetrics,
    staleTime: 10_000,
  });

  return (
    <section className="border border-border rounded-lg bg-surface/40 p-4">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-sm font-semibold text-txt">System metrics</h2>
        <span className="text-2xs text-txt-faint">in-memory · resets on restart</span>
      </div>

      {isLoading && <p className="text-xs text-txt-muted">Loading metrics…</p>}
      {error && (
        <p className="text-xs text-txt-muted">Metrics unavailable.</p>
      )}

      {data && data.ingestion.total === 0 && (
        <p className="text-xs text-txt-muted">
          No ingestions recorded since the backend last started. Ingest an event to populate.
        </p>
      )}

      {data && data.ingestion.total > 0 && (
        <>
          <div className="flex flex-wrap gap-x-8 gap-y-4">
            <Stat label="Ingestions" value={String(data.ingestion.total)} />
            <Stat
              label="Median latency"
              value={formatLatency(data.ingestion.duration_ms.p50)}
              hint={`p95 ${formatLatency(data.ingestion.duration_ms.p95)}`}
            />
            <Stat
              label="p95 latency"
              value={formatLatency(data.ingestion.duration_ms.p95)}
              hint={`max ${formatLatency(data.ingestion.duration_ms.max)}`}
            />
            <Stat
              label="Mean cost"
              value={`$${data.ingestion.cost_usd.mean.toFixed(4)}`}
              hint={`total $${data.ingestion.cost_usd.total.toFixed(4)}`}
            />
          </div>

          <p className="text-2xs text-txt-faint mt-3 leading-relaxed">
            {data.adjudications.resolution_total} resolution adjudication
            {data.adjudications.resolution_total === 1 ? '' : 's'}
            {Object.keys(data.adjudications.resolution_by_tier).length > 0 && (
              <>
                {' '}(
                {Object.entries(data.adjudications.resolution_by_tier)
                  .sort(([a], [b]) => a.localeCompare(b))
                  .map(([tier, n]) => `T${tier}:${n}`)
                  .join(' · ')}
                )
              </>
            )}{' '}
            · {data.adjudications.contradiction_total} contradiction adjudication
            {data.adjudications.contradiction_total === 1 ? '' : 's'}. Tier-2 is the LLM-adjudicated
            band the parallel resolver fans out.
          </p>
        </>
      )}
    </section>
  );
}
