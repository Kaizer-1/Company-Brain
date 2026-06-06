/**
 * Renders the `get_entity` structural-tool result: a small card with the entity's type,
 * properties, and a summary of its outgoing/incoming edge types.
 */

import { Badge, nodeTypeBadge } from '../../ui/Badge';
import type { EntityResult as EntityResultData } from '../../../types';

interface Props {
  data: EntityResultData;
}

function edgeSummary(edges: Record<string, number>): string {
  const parts = Object.entries(edges).map(([t, n]) => `${t}×${n}`);
  return parts.join(', ');
}

export function EntityResult({ data }: Props) {
  if (data.node_type === 'not_found') {
    return (
      <section className="border border-border rounded bg-surface px-4 py-3">
        <p className="text-sm text-txt-muted">
          No entity matching <span className="font-mono text-txt">{data.entity_id}</span> was
          found in the graph.
        </p>
      </section>
    );
  }

  const props = Object.entries(data.properties).filter(
    ([, v]) => v !== null && v !== undefined && v !== '',
  );
  const out = edgeSummary(data.outgoing_edges);
  const inc = edgeSummary(data.incoming_edges);

  return (
    <section className="border border-border rounded bg-surface px-4 py-3 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <Badge variant={nodeTypeBadge(data.node_type)}>{data.node_type}</Badge>
        <span className="font-mono text-xs text-txt">{data.entity_id}</span>
      </div>

      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
        {props.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="font-mono text-2xs text-txt-faint">{k}</dt>
            <dd className="text-txt-muted break-words">{String(v)}</dd>
          </div>
        ))}
      </dl>

      {(out || inc) && (
        <div className="flex flex-col gap-1 text-2xs font-mono text-txt-muted">
          {out && <span>→ outgoing: {out}</span>}
          {inc && <span>← incoming: {inc}</span>}
        </div>
      )}
    </section>
  );
}
