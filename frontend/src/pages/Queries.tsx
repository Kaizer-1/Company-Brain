/**
 * /queries — the Killer Query explorer.
 *
 * Two-pane layout: left sidebar lists the four KQs with parameter inputs.
 * Right pane shows: the question, params form, "Run query" button, the answer,
 * a provenance chain visualisation, and expandable source events.
 */

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { fetchKq1, fetchKq2, fetchKq3, fetchKq4 } from '../api/queries';
import { queryKeys } from '../api/client';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { ProgressBar } from '../components/ui/ProgressBar';
import { ErrorMessage } from '../components/ui/ErrorMessage';
import { EventModal } from '../components/graph/EventModal';
import type {
  BlastRadius,
  ChainOwnerAnswer,
  ChangeTimeline,
  Contradiction,
  QueryResult,
} from '../types';
// Note: Contradiction, BlastRadius, ChangeTimeline now match backend field names exactly.

// ── KQ definitions ────────────────────────────────────────────────────────────

type KqId = 'kq1' | 'kq2' | 'kq3' | 'kq4';

const KQS = [
  {
    id: 'kq1' as KqId,
    label: 'KQ1 — Multi-hop ownership',
    question: 'Who owns the service that depends on the system deprecated by Decision X?',
    whyMatters:
      'Requires traversing 3+ typed hops. RAG retrieves flat chunks by similarity; it cannot follow edges.',
  },
  {
    id: 'kq2' as KqId,
    label: 'KQ2 — Temporal contradiction',
    question: 'Which currently-active decisions are contradicted by discussions in the last month?',
    whyMatters:
      'Requires time-filtered set comparison across two corpora. RAG cannot model logical contradictions.',
  },
  {
    id: 'kq3' as KqId,
    label: 'KQ3 — Blast radius',
    question: 'If the payments service fails, which services, decisions, and people are affected?',
    whyMatters:
      'Requires multi-type graph reachability. RAG does not model structural dependencies.',
  },
  {
    id: 'kq4' as KqId,
    label: 'KQ4 — Change tracking',
    question: 'What has changed about the auth system in the last quarter, and who approved each change?',
    whyMatters:
      'Requires temporal edge traversal and approval attribution. RAG cannot reconstruct change timelines.',
  },
] as const;

// ── Default parameter values ─────────────────────────────────────────────────

const DEFAULTS = {
  kq1: { decision_id: 'D-0006' },
  kq2: { window_days: '30' },
  kq3: { service: 'payments-api', max_depth: '5' },
  kq4: { target: 'auth-service', window_days: '90' },
} as const;

// ── Main page ────────────────────────────────────────────────────────────────

export function Queries() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeKq = (searchParams.get('kq') as KqId) ?? 'kq1';

  const setActiveKq = (kq: KqId) => {
    setSearchParams({ kq });
  };

  return (
    <div className="flex h-page overflow-hidden">
      {/* Left sidebar — KQ list */}
      <aside className="w-80 shrink-0 border-r border-border overflow-y-auto bg-surface">
        <div className="p-4 border-b border-border">
          <h2 className="text-xs font-medium text-txt-muted uppercase tracking-widest">
            Killer Queries
          </h2>
        </div>
        <ul className="p-2 space-y-0.5">
          {KQS.map((kq) => (
            <li key={kq.id}>
              <button
                onClick={() => setActiveKq(kq.id)}
                className={[
                  'w-full text-left px-3 py-2.5 rounded transition-colors duration-150 cursor-pointer group',
                  activeKq === kq.id ? 'bg-s2 text-txt' : 'text-txt-muted hover:text-txt hover:bg-s2',
                ].join(' ')}
              >
                <p className="text-sm font-medium leading-snug">{kq.label}</p>
                <p className="text-xs text-txt-muted mt-0.5 leading-relaxed line-clamp-2">
                  {kq.question}
                </p>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      {/* Right panel — query runner */}
      <div className="flex-1 overflow-y-auto">
        <QueryPanel kqId={activeKq} />
      </div>
    </div>
  );
}

// ── Query panel (right pane) ─────────────────────────────────────────────────

function QueryPanel({ kqId }: { kqId: KqId }) {
  const kq = KQS.find((k) => k.id === kqId)!;

  const [params, setParams] = useState<Record<string, string>>(() => ({
    ...DEFAULTS[kqId],
  }));
  const [triggered, setTriggered] = useState(false);

  const handleRun = () => {
    setTriggered(true);
  };

  return (
    <div className="max-w-3xl p-6 space-y-5">
      {/* Question */}
      <div>
        <Badge variant="muted" className="mb-2">{kq.id.toUpperCase()}</Badge>
        <h1 className="text-xl font-semibold text-txt leading-snug">{kq.question}</h1>
        <p className="text-sm text-txt-muted mt-2 leading-relaxed">
          <span className="text-txt-faint text-xs uppercase tracking-widest mr-1">Why RAG fails:</span>
          {kq.whyMatters}
        </p>
      </div>

      <div className="divider" />

      {/* Params + Run */}
      <div className="flex flex-wrap items-end gap-3">
        <ParamInputs kqId={kqId} params={params} onChange={setParams} />
        <Button onClick={handleRun} size="md">
          Run query
        </Button>
      </div>

      {/* Result — only mounted after first run */}
      {triggered && (
        <QueryResult kqId={kqId} params={params} />
      )}
    </div>
  );
}

// ── Parameter inputs per KQ ──────────────────────────────────────────────────

function ParamInputs({
  kqId,
  params,
  onChange,
}: {
  kqId: KqId;
  params: Record<string, string>;
  onChange: (p: Record<string, string>) => void;
}) {
  const set = (key: string, val: string) => onChange({ ...params, [key]: val });

  const field = (key: string, label: string, placeholder?: string) => (
    <label className="flex flex-col gap-1" key={key}>
      <span className="text-xs text-txt-muted">{label}</span>
      <input
        className="bg-bg border border-border rounded px-2.5 py-1.5 text-sm text-txt font-mono focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-1 focus:ring-offset-bg w-48"
        value={params[key] ?? ''}
        placeholder={placeholder}
        onChange={(e) => set(key, e.target.value)}
      />
    </label>
  );

  switch (kqId) {
    case 'kq1':
      return <>{field('decision_id', 'Decision ID', 'D-0006')}</>;
    case 'kq2':
      return <>{field('window_days', 'Window (days)', '30')}</>;
    case 'kq3':
      return (
        <>
          {field('service', 'Service', 'payments-api')}
          {field('max_depth', 'Max depth', '5')}
        </>
      );
    case 'kq4':
      return (
        <>
          {field('target', 'Target', 'auth-service')}
          {field('window_days', 'Window (days)', '90')}
        </>
      );
  }
}

// ── Result dispatcher ────────────────────────────────────────────────────────

function QueryResult({ kqId, params }: { kqId: KqId; params: Record<string, string> }) {
  switch (kqId) {
    case 'kq1':
      return <Kq1Result decisionId={params.decision_id ?? 'D-0006'} />;
    case 'kq2':
      return <Kq2Result windowDays={Number(params.window_days ?? 30)} />;
    case 'kq3':
      return (
        <Kq3Result
          service={params.service ?? 'payments-api'}
          maxDepth={Number(params.max_depth ?? 5)}
        />
      );
    case 'kq4':
      return (
        <Kq4Result
          target={params.target ?? 'auth-service'}
          windowDays={Number(params.window_days ?? 90)}
        />
      );
  }
}

// ── KQ1 result ───────────────────────────────────────────────────────────────

function Kq1Result({ decisionId }: { decisionId: string }) {
  const { data, isLoading, error } = useQuery<QueryResult<ChainOwnerAnswer>>({
    queryKey: queryKeys.kq1(decisionId),
    queryFn: () => fetchKq1(decisionId),
    staleTime: 0,
  });

  if (isLoading) return <ResultSkeleton />;
  if (error) return <ErrorMessage error={error instanceof Error ? error : new Error(String(error))} />;
  if (!data) return null;

  const a = data.value;
  const ownerPeople = a.owner_people ?? [];
  const chains = a.chains ?? [];
  const kq1EventIds = provenanceIds(data.provenance);

  return (
    <div className="space-y-4">
      {/* Answer headline */}
      <div className="bg-s2 border border-border rounded p-4">
        <p className="text-xs text-txt-muted mb-1">Owner</p>
        <p className="text-lg font-semibold text-txt">
          {ownerPeople.join(', ') || '—'}
        </p>
        {a.decision_title && (
          <p className="text-xs text-txt-muted mt-1 font-mono">{decisionId}: {a.decision_title}</p>
        )}
      </div>

      {/* Traversal chains */}
      {chains.map((chain, i) => (
        <div key={i}>
          <p className="text-xs text-txt-muted mb-2">
            Chain {i + 1} — {(chain.nodes ?? []).length - 1} hops
          </p>
          <ChainViz nodes={chain.nodes ?? []} />
        </div>
      ))}

      <ProvenanceSection eventIds={kq1EventIds} />
    </div>
  );
}

// ── KQ2 result ───────────────────────────────────────────────────────────────

function Kq2Result({ windowDays }: { windowDays: number }) {
  const { data, isLoading, error } = useQuery<QueryResult<Contradiction[]>>({
    queryKey: queryKeys.kq2(windowDays),
    queryFn: () => fetchKq2(windowDays),
    staleTime: 0,
  });

  if (isLoading) return <ResultSkeleton />;
  if (error) return <ErrorMessage error={error instanceof Error ? error : new Error(String(error))} />;
  if (!data) return null;

  const contradictions = data.value ?? [];
  const kq2EventIds = provenanceIds(data.provenance);

  return (
    <div className="space-y-4">
      <div className="bg-s2 border border-border rounded p-4">
        <p className="text-xs text-txt-muted mb-1">Contradicted decisions</p>
        <p className="text-lg font-semibold text-txt">
          {contradictions.length} found
        </p>
      </div>

      {contradictions.length === 0 && (
        <p className="text-sm text-txt-muted">No contradictions in the last {windowDays} days.</p>
      )}

      {contradictions.map((c, i) => (
        <div key={i} className="border border-border rounded p-4 space-y-3">
          <div>
            <Badge variant="warn" className="mb-1">{c.decision_id}</Badge>
            <p className="text-sm font-medium text-txt">
              {c.decision_title ?? c.decision_id}
            </p>
          </div>
          <div className="space-y-2">
            {(c.messages ?? []).map((m, j) => (
              <div key={j} className="bg-bg border border-border rounded p-3 text-xs space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-txt-muted">
                    {m.said_at ? new Date(m.said_at).toLocaleDateString() : '—'}
                  </span>
                  {m.confidence != null && (
                    <span className="font-mono text-amber-400">
                      conf {(m.confidence * 100).toFixed(0)}%
                    </span>
                  )}
                </div>
                <p className="font-mono text-txt-muted">{m.message_id}</p>
              </div>
            ))}
          </div>
        </div>
      ))}

      <ProvenanceSection eventIds={kq2EventIds} />
    </div>
  );
}

// ── KQ3 result ───────────────────────────────────────────────────────────────

function Kq3Result({ service, maxDepth }: { service: string; maxDepth: number }) {
  const { data, isLoading, error } = useQuery<QueryResult<BlastRadius>>({
    queryKey: queryKeys.kq3(service, maxDepth),
    queryFn: () => fetchKq3(service, maxDepth),
    staleTime: 0,
  });

  if (isLoading) return <ResultSkeleton />;
  if (error) return <ErrorMessage error={error instanceof Error ? error : new Error(String(error))} />;
  if (!data) return null;

  const br = data.value;
  const services = br.affected_services ?? [];
  const people = br.affected_people ?? [];
  const decisions = br.affected_decisions ?? [];
  const kq3EventIds = provenanceIds(data.provenance);

  return (
    <div className="space-y-4">
      <div className="bg-s2 border border-border rounded p-4 grid grid-cols-3 gap-4">
        <Stat label="Services" value={services.length} />
        <Stat label="People" value={people.length} />
        <Stat label="Decisions" value={decisions.length} />
      </div>

      <Section title={`Services (${services.length})`}>
        <div className="flex flex-wrap gap-1.5">
          {services.map((s) => (
            <Badge key={s} variant="service">{s}</Badge>
          ))}
        </div>
      </Section>

      {people.length > 0 && (
        <Section title={`People (${people.length})`}>
          <div className="flex flex-wrap gap-1.5">
            {people.map((p) => (
              <Badge key={p} variant="person">{p}</Badge>
            ))}
          </div>
        </Section>
      )}

      {decisions.length > 0 && (
        <Section title={`Decisions (${decisions.length})`}>
          <div className="flex flex-wrap gap-1.5">
            {decisions.map((d) => (
              <Badge key={d} variant="decision">{d}</Badge>
            ))}
          </div>
        </Section>
      )}

      <ProvenanceSection eventIds={kq3EventIds} />
    </div>
  );
}

// ── KQ4 result ───────────────────────────────────────────────────────────────

function Kq4Result({ target, windowDays }: { target: string; windowDays: number }) {
  const { data, isLoading, error } = useQuery<QueryResult<ChangeTimeline>>({
    queryKey: queryKeys.kq4(target, windowDays),
    queryFn: () => fetchKq4(target, windowDays),
    staleTime: 0,
  });

  if (isLoading) return <ResultSkeleton />;
  if (error) return <ErrorMessage error={error instanceof Error ? error : new Error(String(error))} />;
  if (!data) return null;

  const timeline = data.value;
  const entries = timeline.changes ?? [];
  const kq4EventIds = provenanceIds(data.provenance);

  return (
    <div className="space-y-4">
      <div className="bg-s2 border border-border rounded p-4">
        <p className="text-xs text-txt-muted mb-1">Changes to</p>
        <p className="text-lg font-semibold text-txt font-mono">{timeline.target}</p>
        <p className="text-xs text-txt-muted mt-0.5">{entries.length} decisions in window</p>
      </div>

      {/* Vertical timeline */}
      <div className="relative border-l border-border ml-3 pl-5 space-y-4">
        {entries.map((entry) => {
          const supersedes = entry.supersedes ?? [];
          const approvers = entry.approvers ?? [];
          return (
            <div key={entry.decision_id} className="relative">
              <span className="absolute -left-[21px] top-1.5 w-2 h-2 rounded-full bg-accent" />
              <div className="bg-s2 border border-border rounded p-3 space-y-1.5">
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge variant="decision">{entry.decision_id}</Badge>
                  {supersedes.length > 0 && (
                    <span className="text-2xs text-txt-muted font-mono">
                      supersedes {supersedes.join(', ')}
                    </span>
                  )}
                </div>
                {entry.title && (
                  <p className="text-sm font-medium text-txt">{entry.title}</p>
                )}
                <div className="flex items-center gap-3 text-xs text-txt-muted flex-wrap">
                  {entry.valid_from && (
                    <span className="font-mono">
                      {new Date(entry.valid_from).toLocaleDateString()}
                    </span>
                  )}
                  {approvers.length > 0 && (
                    <span>
                      Approved by: {approvers.map((a) => (
                        <span key={a} className="font-mono text-txt ml-1">{a}</span>
                      ))}
                    </span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <ProvenanceSection eventIds={kq4EventIds} />
    </div>
  );
}

// ── Shared result sub-components ─────────────────────────────────────────────

/** Inline provenance chain: A → [EDGE] → B → [EDGE] → C */
function ChainViz({ nodes }: { nodes: string[] }) {
  return (
    <div className="flex flex-wrap items-center gap-1 font-mono text-xs">
      {nodes.map((node, i) => (
        <span key={i} className="flex items-center gap-1">
          <span className="bg-s2 border border-border rounded px-2 py-0.5 text-txt">
            {node}
          </span>
          {i < nodes.length - 1 && (
            <ChevronRight size={12} className="text-txt-faint flex-shrink-0" />
          )}
        </span>
      ))}
    </div>
  );
}

/** Derive event IDs from provenance — falls back to flattening by_element
 *  for backends that don't yet serialize all_event_ids (pre-computed_field fix). */
function provenanceIds(provenance: { all_event_ids?: string[]; by_element?: Record<string, string[]> }): string[] {
  if (provenance.all_event_ids?.length) return provenance.all_event_ids;
  const flat = Object.values(provenance.by_element ?? {}).flat();
  return [...new Set(flat)].sort();
}

function ProvenanceSection({ eventIds }: { eventIds?: string[] }) {
  const [open, setOpen] = useState(false);
  const [openEventId, setOpenEventId] = useState<string | null>(null);

  if (!eventIds?.length) return null;

  return (
    <>
      <div className="border border-border rounded">
        <button
          onClick={() => setOpen((o) => !o)}
          className="w-full flex items-center justify-between px-3 py-2.5 text-sm text-txt-muted hover:text-txt cursor-pointer transition-colors"
        >
          <span>Source events ({eventIds.length})</span>
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
        {open && (
          <div className="border-t border-border px-3 pb-3 pt-2">
            <ul className="space-y-1">
              {eventIds.map((id) => (
                <li key={id}>
                  <button
                    onClick={() => setOpenEventId(id)}
                    className="font-mono text-xs text-txt-muted hover:text-accent cursor-pointer transition-colors"
                  >
                    {id}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {openEventId && (
        <EventModal eventId={openEventId} onClose={() => setOpenEventId(null)} />
      )}
    </>
  );
}

function ResultSkeleton() {
  return (
    <div className="space-y-3">
      <ProgressBar visible />
      <div className="bg-s2 border border-border rounded p-4 h-20 animate-skeleton" />
      <div className="h-12 bg-s2 rounded animate-skeleton" />
      <div className="h-8 w-2/3 bg-s2 rounded animate-skeleton" />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <p className="text-xs text-txt-muted">{label}</p>
      <p className="font-mono text-2xl font-semibold text-txt">{value}</p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-txt-muted">{title}</p>
      {children}
    </div>
  );
}
