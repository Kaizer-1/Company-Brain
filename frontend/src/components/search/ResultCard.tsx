/**
 * A single search result card.
 * Dense data row — no marketing cards, no drop shadows.
 */

import { Badge, nodeTypeBadge } from '../ui/Badge';
import type { SearchHit } from '../../types';

interface ResultCardProps {
  hit: SearchHit;
  rank: number;
  onViewEvent: (id: string) => void;
}

const SOURCE_LABELS: Record<string, string> = {
  doc: 'doc',
  slack_message: 'slack',
};

export function ResultCard({ hit, rank, onViewEvent }: ResultCardProps) {
  const sourceLabel = SOURCE_LABELS[hit.source_kind] ?? hit.source_kind;
  const sourceVariant = hit.source_kind === 'doc' ? 'muted' : 'default';

  return (
    <div className="border border-border rounded bg-surface px-4 py-3 flex flex-col gap-2">
      {/* Header row */}
      <div className="flex items-center gap-2 justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-mono text-2xs text-txt-faint w-5 shrink-0">
            {rank}
          </span>
          <Badge variant={sourceVariant as Parameters<typeof Badge>[0]['variant']}>
            {sourceLabel}
          </Badge>
          <span className="font-mono text-2xs text-txt-muted truncate">
            {hit.source_ref}
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span
            title={`Vector similarity: ${hit.similarity_score.toFixed(3)}`}
            className="font-mono text-2xs text-txt-muted bg-s2 border border-border px-1.5 py-0.5 rounded"
          >
            {hit.similarity_score.toFixed(3)}
          </span>
          <span className="font-mono text-2xs text-txt-faint">
            {new Date(hit.occurred_at).toISOString().slice(0, 10)}
          </span>
        </div>
      </div>

      {/* Snippet */}
      <p className="font-mono text-xs text-txt leading-relaxed line-clamp-3">
        {hit.snippet}
      </p>

      {/* Entity chips + actions */}
      <div className="flex items-center gap-2 flex-wrap justify-between">
        <div className="flex items-center gap-1 flex-wrap">
          {hit.related_entity_ids.slice(0, 6).map((id) => (
            <Badge key={id} variant="muted" className="max-w-[120px] truncate">
              {id}
            </Badge>
          ))}
          {hit.related_entity_ids.length > 6 && (
            <span className="text-2xs text-txt-faint">
              +{hit.related_entity_ids.length - 6}
            </span>
          )}
        </div>
        <button
          onClick={() => onViewEvent(hit.event_id)}
          className="text-2xs text-accent hover:text-accent-hover font-medium shrink-0 cursor-pointer"
        >
          view source
        </button>
      </div>
    </div>
  );
}
