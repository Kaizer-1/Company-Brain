/**
 * Per-stage progress display for the streaming /ask/stream endpoint.
 *
 * Renders each agent stage as it arrives — route badge, tool status, streaming
 * answer text, and verification status. Only shows real events; no fake dots.
 * Once the complete event fires the parent transitions to the full AnswerView.
 */

import type { StreamEvent } from '../../types';
import { Badge } from '../ui/Badge';

const ROUTE_LABELS: Record<string, string> = {
  kq1: 'KQ1 — Multi-hop ownership',
  kq2: 'KQ2 — Temporal contradiction',
  kq3: 'KQ3 — Blast radius',
  kq4: 'KQ4 — Change tracking',
  search: 'Semantic search',
  unknown: 'Out of scope',
};

interface StreamProgressProps {
  /** All SSE events received so far (in arrival order). */
  events: StreamEvent[];
  /** Accumulated synthesis tokens so far (reset to '' on retry). */
  streamingText: string;
}

export function StreamProgress({ events, streamingText }: StreamProgressProps) {
  const routeEvt = events.find((e) => e.type === 'route');
  const toolStartEvt = events.find((e) => e.type === 'tool_start');
  const toolDoneEvt = events.find((e) => e.type === 'tool_done');
  const synthStartEvt = events.findLast((e) => e.type === 'synthesis_start');
  const verifyStartEvt = events.find((e) => e.type === 'verify_start');
  const verifyDoneEvt = events.findLast((e) => e.type === 'verify_done');

  return (
    <div className="flex flex-col gap-3 text-sm font-mono">
      {/* Route classification */}
      {routeEvt && routeEvt.type === 'route' && (
        <div className="flex items-center gap-2">
          <span className="text-accent">✓</span>
          <Badge variant="accent">{ROUTE_LABELS[routeEvt.route] ?? routeEvt.route}</Badge>
          {routeEvt.reasoning && (
            <span className="text-txt-muted text-2xs truncate max-w-xs" title={routeEvt.reasoning}>
              {routeEvt.reasoning}
            </span>
          )}
        </div>
      )}

      {/* Tool execution */}
      {toolStartEvt && toolStartEvt.type === 'tool_start' && (
        <div className="flex items-center gap-2 text-txt-muted">
          {toolDoneEvt ? (
            <span className="text-accent">✓</span>
          ) : (
            <span className="animate-spin inline-block">⟳</span>
          )}
          <span>
            {toolDoneEvt && toolDoneEvt.type === 'tool_done'
              ? `Tool returned: ${toolDoneEvt.tool_output_summary}`
              : `Running ${toolStartEvt.tool}…`}
          </span>
        </div>
      )}

      {/* Synthesis — streaming answer text */}
      {synthStartEvt && (
        <div className="flex flex-col gap-1">
          {synthStartEvt.type === 'synthesis_start' && synthStartEvt.retry && (
            <span className="text-amber-400 text-2xs">Refining answer…</span>
          )}
          {streamingText && (
            <p className="text-txt text-sm leading-relaxed whitespace-pre-wrap">
              {streamingText}
              <span className="animate-pulse ml-px text-accent">▍</span>
            </p>
          )}
          {!streamingText && (
            <span className="text-txt-muted text-2xs animate-pulse">Synthesizing answer…</span>
          )}
        </div>
      )}

      {/* Verification */}
      {verifyStartEvt && !verifyDoneEvt && (
        <span className="text-txt-muted text-2xs animate-pulse">Verifying provenance…</span>
      )}
      {verifyDoneEvt && verifyDoneEvt.type === 'verify_done' && (
        <span className="text-txt-muted text-2xs">
          {verifyDoneEvt.verified
            ? '✓ Provenance verified'
            : '⚠ Verification incomplete — refining…'}
        </span>
      )}
    </div>
  );
}
