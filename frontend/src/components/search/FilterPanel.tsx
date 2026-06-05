/**
 * Left-pane filter controls for the /search page.
 * Multiselect chips for source_kind and entity_type; text inputs for after/before.
 */

import { Button } from '../ui/Button';
import type { SearchFilters } from '../../types';

const SOURCE_KINDS = ['doc', 'slack_message'];
const ENTITY_TYPES = ['Decision', 'Service', 'System', 'Person', 'Team'];

interface FilterPanelProps {
  filters: SearchFilters;
  onChange: (f: SearchFilters) => void;
  onReset: () => void;
}

export function FilterPanel({ filters, onChange, onReset }: FilterPanelProps) {
  function toggleList<T extends string>(
    field: 'source_kind' | 'entity_type',
    value: T,
  ) {
    const current: string[] = (filters[field] as string[] | null | undefined) ?? [];
    const next = current.includes(value)
      ? current.filter((v) => v !== value)
      : [...current, value];
    onChange({ ...filters, [field]: next.length ? next : null });
  }

  function setDate(field: 'after' | 'before', raw: string) {
    onChange({ ...filters, [field]: raw || null });
  }

  const hasAny =
    (filters.source_kind?.length ?? 0) > 0 ||
    (filters.entity_type?.length ?? 0) > 0 ||
    !!filters.after ||
    !!filters.before;

  return (
    <aside className="w-[360px] shrink-0 border-r border-border p-4 flex flex-col gap-5 overflow-y-auto">
      <div>
        <h2 className="text-xs font-medium text-txt-muted uppercase tracking-widest mb-3">
          Source
        </h2>
        <div className="flex flex-wrap gap-1.5">
          {SOURCE_KINDS.map((kind) => {
            const active = (filters.source_kind ?? []).includes(kind);
            return (
              <button
                key={kind}
                onClick={() => toggleList('source_kind', kind)}
                className={[
                  'px-2.5 py-1 rounded text-xs font-mono border transition-colors duration-100',
                  active
                    ? 'bg-accent/10 text-accent border-accent/40'
                    : 'bg-s2 text-txt-muted border-border hover:text-txt hover:border-border',
                ].join(' ')}
              >
                {kind}
              </button>
            );
          })}
        </div>
      </div>

      <div>
        <h2 className="text-xs font-medium text-txt-muted uppercase tracking-widest mb-3">
          Entity type
        </h2>
        <div className="flex flex-wrap gap-1.5">
          {ENTITY_TYPES.map((et) => {
            const active = (filters.entity_type ?? []).includes(et);
            return (
              <button
                key={et}
                onClick={() => toggleList('entity_type', et)}
                className={[
                  'px-2.5 py-1 rounded text-xs border transition-colors duration-100',
                  active
                    ? 'bg-accent/10 text-accent border-accent/40'
                    : 'bg-s2 text-txt-muted border-border hover:text-txt hover:border-border',
                ].join(' ')}
              >
                {et}
              </button>
            );
          })}
        </div>
      </div>

      <div>
        <h2 className="text-xs font-medium text-txt-muted uppercase tracking-widest mb-3">
          Date range
        </h2>
        <div className="flex flex-col gap-2">
          {(['after', 'before'] as const).map((field) => (
            <label key={field} className="flex flex-col gap-1">
              <span className="text-2xs text-txt-muted font-mono">{field}</span>
              <input
                type="date"
                value={filters[field] ? String(filters[field]).slice(0, 10) : ''}
                onChange={(e) => setDate(field, e.target.value)}
                className="bg-s2 border border-border rounded px-2 py-1 text-xs font-mono text-txt focus:outline-none focus:border-accent/60 w-full"
              />
            </label>
          ))}
        </div>
      </div>

      {hasAny && (
        <Button variant="ghost" size="sm" onClick={onReset} className="self-start text-txt-muted">
          Reset filters
        </Button>
      )}
    </aside>
  );
}
