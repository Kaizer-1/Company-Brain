/**
 * react-force-graph-2d canvas wrapper.
 *
 * Uses nodeCanvasObject for custom rendering (colored circles + truncated label)
 * and linkCanvasObject for dashed MERGE_INTO edges. The resolved view suppresses
 * MERGE_INTO edges entirely; the fragmented view draws them as dashed gray lines
 * to visualise the entity-resolution work.
 */

import ForceGraph2D from 'react-force-graph-2d';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { GraphEdge, GraphNode } from '../../types';
import { NODE_COLORS } from './NodeLegend';

// react-force-graph mutates nodes in-place, adding simulation coords.
// We extend with the extra props the library injects.
interface FGNode extends GraphNode {
  x?: number;
  y?: number;
  fx?: number;
  fy?: number;
}

interface FGLink {
  source: string | FGNode;
  target: string | FGNode;
  edge_type: string;
  is_merge_into: boolean;
  id: string;
}

interface GraphCanvasProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onNodeHover: (node: GraphNode | null) => void;
  onNodeClick: (node: GraphNode) => void;
}

const NODE_RADIUS: Record<string, number> = {
  Decision: 7,
  Service:  6,
  System:   5,
  Person:   5,
  Team:     6,
  Message:  4,
};

// Muted edge colors by type — subtle so the graph doesn't look like spaghetti
const EDGE_COLORS: Record<string, string> = {
  DEPENDS_ON:  '#334155',
  OWNED_BY:    '#3F4E66',
  MEMBER_OF:   '#3F4E66',
  DEPRECATES:  '#5C3A0A',
  ABOUT:       '#3F4E66',
  APPROVED_BY: '#3F4E66',
  AUTHORED:    '#3F4E66',
  MENTIONS:    '#3F4E66',
  CONTRADICTS: '#6B2D0A',
  SUPERSEDES:  '#3F3060',
  MERGE_INTO:  '#252D3D',
};

export function GraphCanvas({ nodes, edges, onNodeHover, onNodeClick }: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ w: 800, h: 600 });

  // Measure container and update on resize
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const obs = new ResizeObserver(() => {
      setDims({ w: el.clientWidth, h: el.clientHeight });
    });
    obs.observe(el);
    setDims({ w: el.clientWidth, h: el.clientHeight });
    return () => obs.disconnect();
  }, []);

  // Memoize graphData so its reference only changes when the actual data changes.
  // Without this, every hover triggers a parent re-render which creates a new
  // graphData object reference, causing ForceGraph2D to reheat the simulation.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const graphData: any = useMemo(() => ({
    nodes: nodes as FGNode[],
    links: edges as unknown as FGLink[],
  }), [nodes, edges]);

  const handleNodeHover = useCallback(
    (node: FGNode | null) => {
      onNodeHover(node as GraphNode | null);
    },
    [onNodeHover],
  );

  const handleNodeClick = useCallback(
    (node: FGNode) => {
      onNodeClick(node as GraphNode);
    },
    [onNodeClick],
  );

  const paintNode = useCallback(
    (node: FGNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const r = (NODE_RADIUS[node.node_type] ?? 5);
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      const color = NODE_COLORS[node.node_type as keyof typeof NODE_COLORS] ?? '#64748B';

      // Merged nodes — draw as faint ghost
      const isMerged = node.status === 'merged';
      ctx.globalAlpha = isMerged ? 0.25 : 1;

      // Filled circle
      ctx.beginPath();
      ctx.arc(x, y, r, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();

      // Subtle border ring
      ctx.strokeStyle = color + '40';
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Label — only render when zoomed in enough to avoid clutter
      const labelSize = 11 / globalScale;
      if (globalScale >= 0.8 && labelSize >= 2) {
        ctx.font = `${labelSize}px Inter, system-ui, sans-serif`;
        ctx.fillStyle = isMerged ? '#64748B' : '#CBD5E1';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        const maxChars = Math.floor(60 / globalScale);
        const label =
          node.label.length > maxChars
            ? node.label.slice(0, maxChars - 1) + '…'
            : node.label;
        ctx.fillText(label, x, y + r + 2);
      }

      ctx.globalAlpha = 1;
    },
    [],
  );

  const getLinkColor = useCallback((link: object) => {
    const l = link as unknown as FGLink;
    if (l.is_merge_into) return '#252D3D';
    return EDGE_COLORS[l.edge_type] ?? '#334155';
  }, []);

  const getLinkWidth = useCallback((link: object) => {
    const l = link as unknown as FGLink;
    return l.is_merge_into ? 1 : 1.2;
  }, []);

  // Label on hover — show edge type on link hover
  const getLinkLabel = useCallback((link: object) => {
    return (link as unknown as FGLink).edge_type;
  }, []);

  // Pin every node at its settled position so hover re-renders don't drift.
  // The library mutates nodes in place during simulation, so node.x/y are
  // the settled coords when this fires.
  const handleEngineStop = useCallback(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (graphData.nodes as FGNode[]).forEach((node: any) => {
      node.fx = node.x;
      node.fy = node.y;
    });
  }, [graphData]);

  return (
    <div ref={containerRef} className="w-full h-full">
      <ForceGraph2D
        width={dims.w}
        height={dims.h}
        graphData={graphData}
        nodeId="id"
        nodeLabel="label"
        nodeCanvasObject={paintNode}
        nodeCanvasObjectMode={() => 'replace'}
        linkColor={getLinkColor}
        linkWidth={getLinkWidth}
        linkLabel={getLinkLabel}
        linkDirectionalArrowLength={4}
        linkDirectionalArrowRelPos={1}
        linkDirectionalArrowColor={getLinkColor}
        linkCanvasObjectMode={() => 'after'}
        linkCanvasObject={(link: unknown, ctx: CanvasRenderingContext2D) => {
          const l = link as FGLink;
          if (!l.is_merge_into) return;
          // Re-draw as dashed line (arrow already drawn by default renderer)
          const src = l.source as FGNode;
          const tgt = l.target as FGNode;
          if (!src.x || !src.y || !tgt.x || !tgt.y) return;
          ctx.save();
          ctx.setLineDash([4, 4]);
          ctx.strokeStyle = '#252D3D';
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(src.x, src.y);
          ctx.lineTo(tgt.x, tgt.y);
          ctx.stroke();
          ctx.restore();
        }}
        onNodeHover={handleNodeHover}
        onNodeClick={handleNodeClick}
        onEngineStop={handleEngineStop}
        cooldownTicks={150}
        warmupTicks={20}
        d3AlphaDecay={0.05}
        d3VelocityDecay={0.6}
        backgroundColor="#0C0E12"
      />
    </div>
  );
}
