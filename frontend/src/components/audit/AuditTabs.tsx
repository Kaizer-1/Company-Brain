/**
 * AuditTabs — minimal two-tab segmented control for the /audit page (Phase 5B).
 *
 * Introduced because the page previously rendered a single table. Built from Tailwind
 * primitives (no shadcn), matching the dark palette. The selected tab is owned by the parent
 * (Audit.tsx), which mirrors it into the URL query (?tab=ingestion-runs).
 */

export type AuditTab = 'resolution' | 'ingestion-runs';

const TABS: ReadonlyArray<{ id: AuditTab; label: string }> = [
  { id: 'resolution', label: 'Resolution decisions' },
  { id: 'ingestion-runs', label: 'Ingestion runs' },
];

interface AuditTabsProps {
  active: AuditTab;
  onChange: (tab: AuditTab) => void;
}

export function AuditTabs({ active, onChange }: AuditTabsProps) {
  return (
    <div
      role="tablist"
      aria-label="Audit views"
      className="inline-flex items-center gap-1 p-1 bg-s2 border border-border rounded-lg"
    >
      {TABS.map((tab) => {
        const selected = active === tab.id;
        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(tab.id)}
            className={`px-3 py-1.5 text-xs font-medium rounded-md cursor-pointer transition-colors ${
              selected
                ? 'bg-surface text-txt shadow-sm'
                : 'text-txt-muted hover:text-txt'
            }`}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
