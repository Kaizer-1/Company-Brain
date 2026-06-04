/**
 * /audit — Resolution audit trail.
 *
 * Tabular view of merge_decisions. Filterable by tier (1/2/3), decision type,
 * and node type. LLM reasoning truncated, expandable per row.
 * Sorted newest-first. "Every AI decision is logged" made visible.
 */

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { fetchAudit } from '../api/audit';
import { queryKeys } from '../api/client';
import { Badge } from '../components/ui/Badge';
import { ProgressBar } from '../components/ui/ProgressBar';
import { ErrorMessage } from '../components/ui/ErrorMessage';
import { Skeleton } from '../components/ui/Skeleton';
import type { DecisionType, MergeDecisionDTO } from '../types';

const DECISION_VARIANTS: Record<DecisionType, { label: string; variant: 'success' | 'accent' | 'muted' | 'warn' }> = {
  auto_merge:       { label: 'auto merge',       variant: 'success' },
  llm_merge:        { label: 'LLM merge',         variant: 'accent'  },
  llm_no_merge:     { label: 'LLM no merge',      variant: 'muted'   },
  below_threshold:  { label: 'below threshold',   variant: 'muted'   },
  content_merge:    { label: 'content merge',     variant: 'warn'    },
};

const TIERS = ['', '1', '2', '3'];
const DECISION_TYPES: Array<DecisionType | ''> = [
  '',
  'auto_merge',
  'llm_merge',
  'llm_no_merge',
  'below_threshold',
  'content_merge',
];
const NODE_TYPES = ['', 'Person', 'Service', 'System', 'Team', 'Decision'];

const PAGE_SIZE = 50;

export function Audit() {
  const [tier, setTier] = useState<string>('');
  const [decision, setDecision] = useState<string>('');
  const [nodeType, setNodeType] = useState<string>('');
  const [offset, setOffset] = useState(0);

  const filters = {
    tier: tier ? Number(tier) : null,
    decision: decision || null,
    node_type: nodeType || null,
    limit: PAGE_SIZE,
    offset,
  };

  const cacheKey = queryKeys.audit({
    tier: tier || null,
    decision: decision || null,
    node_type: nodeType || null,
    offset,
  });

  const { data, isLoading, error } = useQuery({
    queryKey: cacheKey,
    queryFn: () => fetchAudit(filters),
    staleTime: 30_000,
  });

  const handleFilterChange = () => setOffset(0); // reset to page 1 on filter change

  return (
    <div className="h-page overflow-y-auto">
      <ProgressBar visible={isLoading} />

      <div className="p-5 space-y-4">
        {/* Page header */}
        <div>
          <h1 className="text-xl font-semibold text-txt">Resolution audit trail</h1>
          <p className="text-sm text-txt-muted mt-1">
            Every entity-resolution decision — auto-merge, LLM-adjudicated, rejected, below
            threshold — logged with tier, similarity score, and reasoning.
          </p>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3">
          <FilterSelect
            label="Tier"
            value={tier}
            options={TIERS.map((t) => ({ value: t, label: t ? `Tier ${t}` : 'All tiers' }))}
            onChange={(v) => { setTier(v); handleFilterChange(); }}
          />
          <FilterSelect
            label="Decision"
            value={decision}
            options={DECISION_TYPES.map((d) => ({
              value: d,
              label: d ? (DECISION_VARIANTS[d as DecisionType]?.label ?? d) : 'All decisions',
            }))}
            onChange={(v) => { setDecision(v); handleFilterChange(); }}
          />
          <FilterSelect
            label="Node type"
            value={nodeType}
            options={NODE_TYPES.map((n) => ({ value: n, label: n || 'All types' }))}
            onChange={(v) => { setNodeType(v); handleFilterChange(); }}
          />

          {data && (
            <span className="font-mono text-xs text-txt-muted ml-auto">
              {data.total} total
            </span>
          )}
        </div>

        {/* Error */}
        {error && (
          <ErrorMessage error={error instanceof Error ? error : new Error(String(error))} />
        )}

        {/* Table */}
        {isLoading && !data ? (
          <TableSkeleton />
        ) : (
          <>
            <AuditTable rows={data?.items ?? []} />

            {/* Pagination */}
            {data && data.total > PAGE_SIZE && (
              <div className="flex items-center justify-between pt-2">
                <span className="font-mono text-xs text-txt-muted">
                  {offset + 1}–{Math.min(offset + PAGE_SIZE, data.total)} of {data.total}
                </span>
                <div className="flex gap-2">
                  <button
                    disabled={offset === 0}
                    onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                    className="text-xs text-accent disabled:text-txt-faint cursor-pointer disabled:cursor-not-allowed hover:text-accent-hover transition-colors"
                  >
                    ← Previous
                  </button>
                  <button
                    disabled={offset + PAGE_SIZE >= data.total}
                    onClick={() => setOffset((o) => o + PAGE_SIZE)}
                    className="text-xs text-accent disabled:text-txt-faint cursor-pointer disabled:cursor-not-allowed hover:text-accent-hover transition-colors"
                  >
                    Next →
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ── Table ─────────────────────────────────────────────────────────────────────

function AuditTable({ rows }: { rows: MergeDecisionDTO[] }) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-txt-muted py-6 text-center">
        No decisions match the current filters.
      </p>
    );
  }

  return (
    <div className="border border-border rounded overflow-hidden">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border bg-s2 text-left">
            <Th>Tier</Th>
            <Th>Decision</Th>
            <Th>Node type</Th>
            <Th>Source → Target</Th>
            <Th>Similarity</Th>
            <Th>Reasoning</Th>
            <Th>Created</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <AuditRow key={row.id} row={row} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AuditRow({ row }: { row: MergeDecisionDTO }) {
  const [open, setOpen] = useState(false);
  const dv = DECISION_VARIANTS[row.decision];

  return (
    <>
      <tr className="border-b border-border hover:bg-s2 transition-colors">
        <Td><span className="font-mono">{row.tier}</span></Td>
        <Td>
          <Badge variant={dv?.variant ?? 'default'}>{dv?.label ?? row.decision}</Badge>
        </Td>
        <Td><span className="font-mono text-txt-muted">{row.node_type}</span></Td>
        <Td>
          <div className="font-mono text-txt-muted space-y-0.5">
            <div className="truncate max-w-[160px]" title={row.source_node_id}>
              {row.source_node_id}
            </div>
            <div className="text-txt-faint">↓</div>
            <div className="truncate max-w-[160px]" title={row.target_node_id}>
              {row.target_node_id}
            </div>
          </div>
        </Td>
        <Td>
          {row.embedding_similarity != null ? (
            <span className="font-mono text-txt">
              {(row.embedding_similarity * 100).toFixed(1)}%
            </span>
          ) : (
            <span className="text-txt-faint">—</span>
          )}
        </Td>
        <Td>
          {row.llm_reasoning ? (
            <button
              onClick={() => setOpen((o) => !o)}
              className="flex items-center gap-1 text-txt-muted hover:text-txt cursor-pointer transition-colors"
            >
              {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
              <span>{open ? 'Collapse' : 'Expand'}</span>
            </button>
          ) : (
            <span className="text-txt-faint">—</span>
          )}
        </Td>
        <Td>
          <span className="font-mono text-txt-muted">
            {new Date(row.created_at).toLocaleDateString()}
          </span>
        </Td>
      </tr>

      {open && row.llm_reasoning && (
        <tr className="border-b border-border">
          <td colSpan={7} className="px-3 pb-3 pt-2">
            <div className="bg-bg border border-border rounded p-3">
              <p className="text-2xs text-txt-muted mb-1 font-mono uppercase tracking-widest">
                LLM reasoning {row.llm_model && `· ${row.llm_model}`}
              </p>
              <p className="text-xs text-txt leading-relaxed whitespace-pre-wrap">
                {row.llm_reasoning}
              </p>
              {row.rules_matched.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {row.rules_matched.map((r) => (
                    <Badge key={r} variant="muted">{r}</Badge>
                  ))}
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
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

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex items-center gap-2">
      <span className="text-xs text-txt-muted">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-bg border border-border rounded px-2 py-1 text-xs text-txt focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-1 focus:ring-offset-bg cursor-pointer"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function TableSkeleton() {
  return (
    <div className="border border-border rounded overflow-hidden">
      <div className="bg-s2 h-10 border-b border-border" />
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="px-3 py-2.5 border-b border-border">
          <Skeleton className="h-4 w-full" />
        </div>
      ))}
    </div>
  );
}
