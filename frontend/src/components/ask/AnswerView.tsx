/**
 * Renders the agent's answer prose, replacing inline `[evt:UUID]` provenance markers with
 * clickable superscript numbers (¹ ² ³ …) that match the numbered Sources list. Clicking a
 * superscript opens the EventModal for that event. UUIDs with no resolved citation (rare —
 * the backend strips fabricated ones) render as a muted superscript "?" that is not clickable.
 *
 * When ``streaming=true`` the citation regex is NOT applied — the answer text is still
 * accumulating and a partial UUID would match mid-token, causing flicker. The parent
 * should pass ``streaming=false`` once the ``complete`` SSE event arrives.
 */

import { Fragment } from 'react';
import type { Citation } from '../../types';

interface AnswerViewProps {
  answer: string;
  citations: Citation[];
  onCiteClick: (eventId: string) => void;
  /** When true, render raw text without citation substitution (stream still in progress). */
  streaming?: boolean;
}

const EVT_RE = /\[evt:\s*([^\]]+?)\s*\]/g;

export function AnswerView({ answer, citations, onCiteClick, streaming = false }: AnswerViewProps) {
  // During streaming the answer is still accumulating; skip citation rendering to
  // avoid flicker from partial UUID matches.
  if (streaming) {
    return <p className="text-sm leading-relaxed text-txt whitespace-pre-wrap">{answer}</p>;
  }

  // Map event_id → 1-based citation index for superscript numbering.
  const indexById = new Map<string, number>();
  citations.forEach((c, i) => indexById.set(c.event_id, i + 1));

  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  EVT_RE.lastIndex = 0;
  while ((match = EVT_RE.exec(answer)) !== null) {
    const [full, rawId] = match;
    const eventId = rawId.trim();
    // Push the text before this marker.
    if (match.index > lastIndex) {
      parts.push(<Fragment key={key++}>{answer.slice(lastIndex, match.index)}</Fragment>);
    }
    const num = indexById.get(eventId);
    if (num !== undefined) {
      parts.push(
        <sup
          key={key++}
          role="button"
          tabIndex={0}
          onClick={() => onCiteClick(eventId)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') onCiteClick(eventId);
          }}
          title={`Source ${num}`}
          className="cursor-pointer text-accent hover:underline font-mono text-2xs px-0.5 align-super"
        >
          {num}
        </sup>,
      );
    } else {
      parts.push(
        <sup key={key++} className="text-txt-faint font-mono text-2xs px-0.5" title="Unresolved citation">
          ?
        </sup>,
      );
    }
    lastIndex = match.index + full.length;
  }
  // Trailing text.
  if (lastIndex < answer.length) {
    parts.push(<Fragment key={key++}>{answer.slice(lastIndex)}</Fragment>);
  }

  return <p className="text-sm leading-relaxed text-txt whitespace-pre-wrap">{parts}</p>;
}
