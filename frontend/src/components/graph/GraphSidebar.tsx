import { useState } from 'react';
import type { GraphNode } from '../../types';
import { Badge, nodeTypeBadge } from '../ui/Badge';
import { EventModal } from './EventModal';
import { NODE_COLORS } from './NodeLegend';

interface GraphSidebarProps {
  nodeCount: number;
  edgeCount: number;
  countsByType: Record<string, number>;
  hoveredNode: GraphNode | null;
  selectedNode: GraphNode | null;
  view: 'resolved' | 'fragmented';
  onViewChange: (v: 'resolved' | 'fragmented') => void;
}

export function GraphSidebar({
  nodeCount,
  edgeCount,
  countsByType,
  hoveredNode,
  selectedNode,
  view,
  onViewChange,
}: GraphSidebarProps) {
  const [openEventId, setOpenEventId] = useState<string | null>(null);

  const displayNode = selectedNode ?? hoveredNode;

  return (
    <>
      <aside className="w-80 shrink-0 border-l border-border bg-surface flex flex-col overflow-y-auto">
        {/* View toggle */}
        <div className="p-4 border-b border-border space-y-3">
          <div className="flex items-center gap-1 bg-bg rounded p-1">
            {(['resolved', 'fragmented'] as const).map((v) => (
              <button
                key={v}
                onClick={() => onViewChange(v)}
                className={[
                  'flex-1 px-2 py-1 text-xs rounded transition-colors duration-150 cursor-pointer',
                  view === v
                    ? 'bg-s2 text-txt'
                    : 'text-txt-muted hover:text-txt',
                ].join(' ')}
              >
                {v}
              </button>
            ))}
          </div>

          {view === 'fragmented' && (
            <p className="text-2xs text-txt-muted leading-relaxed">
              Dashed lines show MERGE_INTO edges — entity resolution collapsed
              these fragments into canonical nodes.
            </p>
          )}
        </div>

        {/* Stats — real numbers, monospace */}
        <div className="p-4 border-b border-border space-y-2">
          <div className="flex justify-between items-baseline">
            <span className="text-xs text-txt-muted">Nodes</span>
            <span className="font-mono text-sm text-txt">{nodeCount}</span>
          </div>
          <div className="flex justify-between items-baseline">
            <span className="text-xs text-txt-muted">Edges</span>
            <span className="font-mono text-sm text-txt">{edgeCount}</span>
          </div>
          <div className="divider pt-1" />
          {Object.entries(countsByType).map(([type, count]) => (
            <div key={type} className="flex justify-between items-center">
              <div className="flex items-center gap-1.5">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: NODE_COLORS[type as keyof typeof NODE_COLORS] ?? '#64748B' }}
                />
                <span className="text-xs text-txt-muted">{type}</span>
              </div>
              <span className="font-mono text-xs text-txt">{count}</span>
            </div>
          ))}
        </div>

        {/* Node detail */}
        <div className="flex-1 p-4">
          {displayNode ? (
            <NodeDetail node={displayNode} onViewEvent={setOpenEventId} />
          ) : (
            <p className="text-xs text-txt-faint">
              Hover a node to inspect · Click to pin
            </p>
          )}
        </div>
      </aside>

      {openEventId && (
        <EventModal eventId={openEventId} onClose={() => setOpenEventId(null)} />
      )}
    </>
  );
}

function NodeDetail({
  node,
  onViewEvent,
}: {
  node: GraphNode;
  onViewEvent: (id: string) => void;
}) {
  const [eventsOpen, setEventsOpen] = useState(false);

  return (
    <div className="space-y-3">
      <div>
        <Badge variant={nodeTypeBadge(node.node_type)}>{node.node_type}</Badge>
        <h3 className="mt-1.5 text-sm font-medium text-txt leading-snug">{node.label}</h3>
        {node.canonical_id && node.canonical_id !== node.label && (
          <p className="font-mono text-2xs text-txt-muted mt-0.5">{node.canonical_id}</p>
        )}
      </div>

      <div className="space-y-1">
        <Row label="Status" value={node.status} mono />
        <Row label="Source events" value={String(node.source_event_ids.length)} mono />
      </div>

      {node.source_event_ids.length > 0 && (
        <div>
          <button
            onClick={() => setEventsOpen((o) => !o)}
            className="text-xs text-accent hover:text-accent-hover cursor-pointer transition-colors"
          >
            {eventsOpen ? '▾' : '▸'} Source events ({node.source_event_ids.length})
          </button>

          {eventsOpen && (
            <ul className="mt-2 space-y-1">
              {node.source_event_ids.map((id) => (
                <li key={id}>
                  <button
                    onClick={() => onViewEvent(id)}
                    className="font-mono text-2xs text-txt-muted hover:text-accent cursor-pointer transition-colors truncate block max-w-full text-left"
                    title={id}
                  >
                    {id.slice(0, 8)}…
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function Row({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-xs text-txt-muted shrink-0">{label}</span>
      <span className={`${mono ? 'font-mono' : ''} text-xs text-txt truncate`}>{value}</span>
    </div>
  );
}
