/**
 * Renders the reconciliation result after an ingest: a status banner, the per-stage timeline,
 * and the "what changed" panels (nodes / merges / edges / contradictions). This is the visible
 * demo artifact — what a viewer watches update when an event is injected live.
 */

import { Link } from 'react-router-dom';
import { Badge } from '../ui/Badge';
import type {
  IngestEventResponse,
  StageResult,
  StageStatus,
} from '../../types';

const STAGE_DOT: Record<StageStatus, string> = {
  ok: 'bg-emerald-400',
  skipped: 'bg-zinc-600',
  failed: 'bg-red-400',
};

const NODE_VARIANT: Record<string, 'decision' | 'service' | 'system' | 'person' | 'team' | 'message' | 'default'> = {
  Decision: 'decision',
  Service: 'service',
  System: 'system',
  Person: 'person',
  Team: 'team',
  Message: 'message',
};

function nodeVariant(label: string) {
  return NODE_VARIANT[label] ?? 'default';
}

function StatusBanner({ result }: { result: IngestEventResponse }) {
  const secs = (result.duration_ms / 1000).toFixed(1);
  const cost = `$${result.cost_usd.toFixed(4)}`;
  if (result.deduplicated) {
    return (
      <div className="rounded border border-border bg-s2 px-4 py-3 text-sm text-txt-muted">
        <span className="text-txt font-medium">Already ingested.</span> This event was reconciled
        previously — returning its existing result (idempotent, no re-processing).
      </div>
    );
  }
  if (result.status === 'reconciled') {
    return (
      <div className="rounded border border-emerald-800/40 bg-emerald-950/40 px-4 py-3 text-sm text-emerald-300">
        <span className="font-medium">Reconciled in {secs}s</span> · {cost}
      </div>
    );
  }
  if (result.status === 'partial') {
    const failed = result.stages_run.filter((s) => s.status === 'failed').length;
    return (
      <div className="rounded border border-amber-800/40 bg-amber-950/40 px-4 py-3 text-sm text-amber-300">
        <span className="font-medium">Partial reconciliation</span> · {failed} stage
        {failed === 1 ? '' : 's'} failed · {secs}s · {cost}
      </div>
    );
  }
  return (
    <div className="rounded border border-red-800/40 bg-red-950/40 px-4 py-3 text-sm text-red-300">
      <span className="font-medium">Reconciliation failed</span> · {secs}s
    </div>
  );
}

function StageTimeline({ stages }: { stages: StageResult[] }) {
  return (
    <div>
      <h3 className="text-2xs font-mono uppercase tracking-wide text-txt-muted mb-2">Stages</h3>
      <ol className="space-y-1.5">
        {stages.map((s) => (
          <li key={s.name} className="flex items-start gap-3 text-sm">
            <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${STAGE_DOT[s.status]}`} />
            <span className="font-mono text-txt w-40 shrink-0">{s.name}</span>
            <span
              className={
                s.status === 'failed'
                  ? 'text-red-400 w-16 shrink-0'
                  : s.status === 'skipped'
                    ? 'text-txt-faint w-16 shrink-0'
                    : 'text-emerald-400 w-16 shrink-0'
              }
            >
              {s.status}
            </span>
            <span className="text-txt-muted flex-1">{s.detail}</span>
            <span className="font-mono text-2xs text-txt-faint shrink-0">
              {s.duration_ms.toFixed(0)}ms
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function ChangePanel({ result }: { result: IngestEventResponse }) {
  const empty =
    result.nodes_created.length === 0 &&
    result.nodes_merged.length === 0 &&
    result.edges_created.length === 0 &&
    result.contradictions_detected.length === 0;

  return (
    <div>
      <h3 className="text-2xs font-mono uppercase tracking-wide text-txt-muted mb-2">
        What changed
      </h3>
      {empty ? (
        <p className="text-sm text-txt-faint">
          No graph changes — the event reconciled with nothing to assert.
        </p>
      ) : (
        <div className="space-y-3 text-sm">
          {result.nodes_created.length > 0 && (
            <div>
              <span className="text-txt-muted">Nodes touched: </span>
              <span className="inline-flex flex-wrap gap-1.5 align-middle">
                {result.nodes_created.map((n) => (
                  <Badge key={`${n.label}:${n.id}`} variant={nodeVariant(n.label)}>
                    {n.label} · {n.display_name}
                  </Badge>
                ))}
              </span>
            </div>
          )}
          {result.nodes_merged.length > 0 && (
            <div>
              <span className="text-txt-muted">Merges: </span>
              {result.nodes_merged.map((m) => (
                <span key={`${m.loser_id}->${m.winner_id}`} className="font-mono text-2xs text-txt">
                  {m.loser_id} → {m.winner_id} (tier {m.tier}){' '}
                </span>
              ))}
            </div>
          )}
          {result.edges_created.length > 0 && (
            <div>
              <span className="text-txt-muted">Edges: </span>
              {result.edges_created.map((e, i) => (
                <span key={i} className="font-mono text-2xs text-txt">
                  {e.source_id} —{e.type}→ {e.target_id}{'  '}
                </span>
              ))}
            </div>
          )}
          {result.contradictions_detected.length > 0 && (
            <div>
              <span className="text-txt-muted">Contradictions: </span>
              {result.contradictions_detected.map((c, i) => (
                <Badge key={i} variant="warn" className="mr-1.5">
                  {c.message_id} ⊥ {c.decision_id}
                </Badge>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function ReconciliationView({ result }: { result: IngestEventResponse }) {
  return (
    <div className="space-y-5">
      <StatusBanner result={result} />
      <StageTimeline stages={result.stages_run} />
      <ChangePanel result={result} />
      <Link
        to="/graph"
        className="inline-block text-sm text-accent hover:text-accent-hover transition-colors"
      >
        View in graph →
      </Link>
    </div>
  );
}
