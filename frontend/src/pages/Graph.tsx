import { useQuery } from '@tanstack/react-query';
import { useState, useCallback, useMemo } from 'react';
import { fetchGraph } from '../api/graph';
import { queryKeys } from '../api/client';
import { GraphCanvas } from '../components/graph/GraphCanvas';
import { GraphSidebar } from '../components/graph/GraphSidebar';
import { NodeLegend } from '../components/graph/NodeLegend';
import { ProgressBar } from '../components/ui/ProgressBar';
import { ErrorMessage } from '../components/ui/ErrorMessage';
import type { GraphNode } from '../types';

export function Graph() {
  const [view, setView] = useState<'resolved' | 'fragmented'>('resolved');
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.graph(view),
    queryFn: () => fetchGraph(view),
    staleTime: 30_000,
  });

  const handleNodeHover = useCallback((node: GraphNode | null) => {
    setHoveredNode(node);
  }, []);

  const handleNodeClick = useCallback((node: GraphNode) => {
    setSelectedNode((prev) => (prev?.id === node.id ? null : node));
  }, []);

  const handleViewChange = useCallback((v: 'resolved' | 'fragmented') => {
    setView(v);
    setSelectedNode(null);
    setHoveredNode(null);
  }, []);

  const countsByType = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const n of data?.nodes ?? []) {
      counts[n.node_type] = (counts[n.node_type] ?? 0) + 1;
    }
    return counts;
  }, [data]);

  return (
    <div className="flex h-page overflow-hidden">
      <ProgressBar visible={isLoading} />

      {/* Graph canvas — fills remaining width */}
      <div className="flex-1 relative">
        {error ? (
          <div className="p-6">
            <ErrorMessage error={error instanceof Error ? error : new Error(String(error))} />
          </div>
        ) : (
          <GraphCanvas
            nodes={data?.nodes ?? []}
            edges={data?.edges ?? []}
            onNodeHover={handleNodeHover}
            onNodeClick={handleNodeClick}
          />
        )}

        {/* Bottom-left legend */}
        {!error && <NodeLegend />}

        {/* Empty state hint while loading */}
        {isLoading && !data && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <p className="text-sm text-txt-muted">Loading graph…</p>
          </div>
        )}
      </div>

      {/* Right sidebar */}
      <GraphSidebar
        nodeCount={data?.nodes.length ?? 0}
        edgeCount={data?.edges.length ?? 0}
        countsByType={countsByType}
        hoveredNode={hoveredNode}
        selectedNode={selectedNode}
        view={view}
        onViewChange={handleViewChange}
      />
    </div>
  );
}
