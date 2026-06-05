/**
 * The "Show agent trace" disclosure below the Sources. Expands to show how the agent
 * arrived at its answer: the route it picked, the classifier's reasoning, retry count,
 * and per-node timings. Uses the native <details> element — no extra state needed.
 */

import type { AgentStateDump } from '../../types';

interface AgentTraceProps {
  debug: AgentStateDump;
}

const ROUTE_LABELS: Record<string, string> = {
  kq1: 'KQ1 — Multi-hop ownership',
  kq2: 'KQ2 — Temporal contradiction',
  kq3: 'KQ3 — Blast radius',
  kq4: 'KQ4 — Change tracking',
  search: 'Semantic search',
  unknown: 'Out of scope',
};

export function AgentTrace({ debug }: AgentTraceProps) {
  return (
    <details className="border border-border rounded bg-surface text-xs">
      <summary className="cursor-pointer select-none px-3 py-2 text-txt-muted hover:text-txt font-mono text-2xs">
        Show agent trace
      </summary>
      <div className="px-3 pb-3 pt-1 flex flex-col gap-3 border-t border-border">
        <TraceRow label="route">
          {ROUTE_LABELS[debug.route] ?? debug.route}
        </TraceRow>
        <TraceRow label="reasoning">
          <span className="text-txt-muted">{debug.route_reasoning}</span>
        </TraceRow>
        {Object.keys(debug.tool_input).length > 0 && (
          <TraceRow label="tool_input">
            <code className="font-mono text-2xs text-txt-muted">{JSON.stringify(debug.tool_input)}</code>
          </TraceRow>
        )}
        <TraceRow label="verified">
          <span className={debug.verified ? 'text-emerald-400' : 'text-amber-400'}>
            {String(debug.verified)}
          </span>
          {debug.retry_count > 0 && (
            <span className="text-txt-faint"> · {debug.retry_count} retr{debug.retry_count === 1 ? 'y' : 'ies'}</span>
          )}
        </TraceRow>
        {debug.error && (
          <TraceRow label="error">
            <span className="text-amber-400">{debug.error}</span>
          </TraceRow>
        )}
        <TraceRow label="timings">
          <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-2xs text-txt-muted">
            {Object.entries(debug.timings_ms).map(([stage, ms]) => (
              <span key={stage}>
                {stage} <span className="text-txt-faint">{ms.toFixed(0)}ms</span>
              </span>
            ))}
          </div>
        </TraceRow>
      </div>
    </details>
  );
}

function TraceRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3">
      <span className="font-mono text-2xs text-txt-faint w-20 shrink-0 pt-0.5">{label}</span>
      <div className="text-xs text-txt min-w-0">{children}</div>
    </div>
  );
}
