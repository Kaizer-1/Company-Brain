import type { NodeType } from '../../types';

const NODE_COLORS: Record<NodeType, string> = {
  Decision: '#D97706',
  Service:  '#3B82F6',
  System:   '#71717A',
  Person:   '#34D399',
  Team:     '#A78BFA',
  Message:  '#94A3B8',
};

export function NodeLegend() {
  return (
    <div className="absolute bottom-4 left-4 bg-surface/90 backdrop-blur-sm border border-border rounded p-2.5 space-y-1.5 select-none pointer-events-none">
      {(Object.entries(NODE_COLORS) as [NodeType, string][]).map(([type, color]) => (
        <div key={type} className="flex items-center gap-2">
          <span
            className="w-2.5 h-2.5 rounded-full flex-shrink-0"
            style={{ backgroundColor: color }}
          />
          <span className="text-2xs text-txt-muted font-mono">{type}</span>
        </div>
      ))}
    </div>
  );
}

export { NODE_COLORS };
