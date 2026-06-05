/**
 * The numbered "Sources" list below the answer. Numbering matches the inline superscripts
 * in AnswerView. Each row is clickable, opening the EventModal for that event.
 */

import { Badge } from '../ui/Badge';
import type { Citation } from '../../types';

interface CitationListProps {
  citations: Citation[];
  onSelect: (eventId: string) => void;
}

const SOURCE_LABELS: Record<string, string> = {
  doc: 'doc',
  slack_message: 'slack',
};

export function CitationList({ citations, onSelect }: CitationListProps) {
  if (citations.length === 0) return null;

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-2xs font-mono uppercase tracking-wide text-txt-faint">Sources</h2>
      <ol className="flex flex-col gap-2">
        {citations.map((c, i) => (
          <li key={c.event_id}>
            <button
              onClick={() => onSelect(c.event_id)}
              className="w-full text-left border border-border rounded bg-surface px-3 py-2 flex gap-3 items-start hover:border-accent/40 hover:bg-s2 transition-colors duration-150 cursor-pointer"
            >
              <span className="font-mono text-2xs text-accent w-4 shrink-0 pt-0.5">{i + 1}</span>
              <div className="flex flex-col gap-1 min-w-0">
                <div className="flex items-center gap-2">
                  <Badge variant="muted">{SOURCE_LABELS[c.source_kind] ?? c.source_kind}</Badge>
                  <span className="font-mono text-2xs text-txt-muted truncate">{c.source_ref}</span>
                </div>
                <p className="text-2xs text-txt-muted leading-snug line-clamp-2">{c.snippet}</p>
              </div>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
