/**
 * Renders the `aggregate` structural-tool result: a single total when ungrouped, or a
 * compact group/count table when grouped by a relationship.
 */

import { Badge, nodeTypeBadge } from '../../ui/Badge';
import type { AggregateResult as AggregateResultData } from '../../../types';

interface Props {
  data: AggregateResultData;
}

export function AggregateResult({ data }: Props) {
  const groups = data.groups ?? [];
  const max = groups.reduce((m, g) => Math.max(m, g.count), 0);

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <Badge variant={nodeTypeBadge(data.node_type)}>{data.node_type}</Badge>
        <span className="font-mono text-2xs text-txt-muted">total: {data.total}</span>
      </div>

      {groups.length > 0 && (
        <table className="w-full text-xs">
          <tbody>
            {groups.map((g) => (
              <tr key={`${g.group_type}:${g.group_name}`} className="border-b border-border/50">
                <td className="py-1 pr-3 font-mono text-txt-muted">{g.group_name}</td>
                <td className="py-1 pr-3">
                  <Badge variant={nodeTypeBadge(g.group_type)}>{g.group_type}</Badge>
                </td>
                <td className="py-1 w-1/2">
                  <div className="flex items-center gap-2">
                    <div
                      className="h-1.5 rounded bg-accent/60"
                      style={{ width: `${max > 0 ? (g.count / max) * 100 : 0}%` }}
                    />
                    <span className="font-mono text-2xs text-txt">{g.count}</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
