/**
 * Renders the `enumerate` structural-tool result: the full list of returned nodes with a
 * truncation note when total_count exceeds returned_count. Each row links into the graph.
 */

import { Link } from 'react-router-dom';
import { Badge, nodeTypeBadge } from '../../ui/Badge';
import type { EnumerateResult as EnumerateResultData } from '../../../types';

interface Props {
  data: EnumerateResultData;
}

function extraSummary(extra: Record<string, unknown>): string {
  const keep = ['email', 'handle', 'title', 'valid_from', 'valid_to', 'formerly'];
  const parts: string[] = [];
  for (const k of keep) {
    const v = extra[k];
    if (v !== undefined && v !== null && v !== '') parts.push(`${k}: ${String(v)}`);
  }
  return parts.join(' · ');
}

export function EnumerateResult({ data }: Props) {
  const truncated = data.total_count > data.returned_count;

  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <Badge variant={nodeTypeBadge(data.node_type)}>{data.node_type}</Badge>
        <span className="font-mono text-2xs text-txt-muted">
          {truncated
            ? `showing ${data.returned_count} of ${data.total_count}`
            : `${data.total_count} total`}
        </span>
      </div>

      <ul className="flex flex-col gap-1">
        {data.nodes.map((n) => {
          const summary = extraSummary(n.extra_fields);
          return (
            <li
              key={n.id}
              className="border border-border rounded bg-surface px-3 py-2 flex items-center gap-3"
            >
              <Link
                to={`/graph?focus=${encodeURIComponent(n.id)}`}
                className="font-mono text-xs text-accent hover:underline shrink-0"
              >
                {n.name}
              </Link>
              {n.status && n.status !== 'active' && (
                <Badge variant="muted">{n.status}</Badge>
              )}
              {summary && (
                <span className="text-2xs text-txt-muted truncate">{summary}</span>
              )}
            </li>
          );
        })}
      </ul>

      {truncated && (
        <p className="text-2xs text-txt-faint font-mono">
          Refine the filters (status, team, limit) to narrow this list.
        </p>
      )}
    </section>
  );
}
