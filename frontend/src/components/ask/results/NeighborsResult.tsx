/**
 * Renders the `neighbors` structural-tool result: neighbour rows grouped by edge type, each
 * with the neighbour's name/type, traversal direction, and a link into the graph.
 */

import { Link } from 'react-router-dom';
import { Badge, nodeTypeBadge } from '../../ui/Badge';
import type { NeighborItem, NeighborsResult as NeighborsResultData } from '../../../types';

interface Props {
  data: NeighborsResultData;
}

function groupByEdge(neighbors: NeighborItem[]): Record<string, NeighborItem[]> {
  const groups: Record<string, NeighborItem[]> = {};
  for (const n of neighbors) {
    (groups[n.edge_type] ??= []).push(n);
  }
  return groups;
}

export function NeighborsResult({ data }: Props) {
  if (data.total_count === 0) {
    return (
      <section className="border border-border rounded bg-surface px-4 py-3">
        <p className="text-sm text-txt-muted">
          <span className="font-mono text-txt">{data.entity_id}</span> has no matching
          neighbours in the graph.
        </p>
      </section>
    );
  }

  const groups = groupByEdge(data.neighbors);

  return (
    <section className="flex flex-col gap-3">
      <span className="font-mono text-2xs text-txt-muted">
        {data.total_count} neighbour{data.total_count === 1 ? '' : 's'} of{' '}
        <span className="text-txt">{data.entity_id}</span>
      </span>

      {Object.entries(groups).map(([edge, items]) => (
        <div key={edge} className="flex flex-col gap-1">
          <span className="font-mono text-2xs uppercase tracking-wide text-txt-faint">
            {edge}
          </span>
          <ul className="flex flex-col gap-1">
            {items.map((n) => (
              <li
                key={`${n.edge_type}:${n.neighbor_id}:${n.outgoing}`}
                className="border border-border rounded bg-surface px-3 py-2 flex items-center gap-2"
              >
                <span className="text-accent text-2xs font-mono">{n.outgoing ? '→' : '←'}</span>
                <Badge variant={nodeTypeBadge(n.neighbor_type)}>{n.neighbor_type}</Badge>
                <Link
                  to={`/graph?focus=${encodeURIComponent(n.neighbor_id)}`}
                  className="font-mono text-xs text-txt hover:text-accent hover:underline truncate"
                >
                  {n.neighbor_name}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}
