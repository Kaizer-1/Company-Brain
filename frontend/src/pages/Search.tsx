/**
 * /search — hybrid semantic + graph search page.
 *
 * Two-pane layout matching /queries:
 *   Left (~360px): search input + filter controls
 *   Right: ranked result cards with source drilldown via EventModal
 */

import { useMutation } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { runSearch } from '../api/search';
import { FilterPanel } from '../components/search/FilterPanel';
import { ResultCard } from '../components/search/ResultCard';
import { EventModal } from '../components/graph/EventModal';
import { Button } from '../components/ui/Button';
import { ErrorMessage } from '../components/ui/ErrorMessage';
import { Skeleton } from '../components/ui/Skeleton';
import type { SearchFilters, SearchResult } from '../types';

const EMPTY_FILTERS: SearchFilters = {
  source_kind: null,
  after: null,
  before: null,
  entity_type: null,
};

export function Search() {
  const [query, setQuery] = useState('');
  const [filters, setFilters] = useState<SearchFilters>(EMPTY_FILTERS);
  const [submittedQuery, setSubmittedQuery] = useState('');
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const mutation = useMutation<SearchResult, Error, void>({
    mutationFn: () =>
      runSearch({
        query,
        k: 10,
        filters: _hasFilters(filters) ? filters : null,
      }),
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setSubmittedQuery(query.trim());
    mutation.mutate();
  }

  const result = mutation.data;
  const isLoading = mutation.isPending;
  const error = mutation.error;

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left pane: input + filters */}
      <FilterPanel
        filters={filters}
        onChange={setFilters}
        onReset={() => setFilters(EMPTY_FILTERS)}
      />

      {/* Right pane: query box + results */}
      <main className="flex-1 overflow-y-auto p-6 flex flex-col gap-5 min-w-0">
        {/* Search form */}
        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. decisions about authentication migration"
            className="flex-1 bg-s2 border border-border rounded px-3 py-2 text-sm font-mono text-txt placeholder:text-txt-faint focus:outline-none focus:border-accent/60"
            autoFocus
          />
          <Button type="submit" loading={isLoading} disabled={!query.trim()}>
            Search
          </Button>
        </form>

        {/* Timing bar */}
        {result && (
          <div className="flex items-center gap-4 text-2xs font-mono text-txt-faint">
            <span>{result.total_candidates} candidates</span>
            <span>embed {result.query_embedding_ms.toFixed(0)}ms</span>
            <span>vector {result.vector_search_ms.toFixed(0)}ms</span>
            <span>rerank {result.rerank_ms.toFixed(0)}ms</span>
            <span className="text-txt-muted">total {result.total_ms.toFixed(0)}ms</span>
          </div>
        )}

        {/* Error */}
        <ErrorMessage error={error} />

        {/* Loading skeletons */}
        {isLoading && (
          <div className="flex flex-col gap-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-20 rounded" />
            ))}
          </div>
        )}

        {/* Empty state */}
        {!isLoading && result && result.hits.length === 0 && (
          <p className="text-sm text-txt-muted font-mono">
            No results for <span className="text-txt">"{submittedQuery}"</span>.
            {_hasFilters(filters) && ' Try removing filters.'}
          </p>
        )}

        {/* Results */}
        {!isLoading && result && result.hits.length > 0 && (
          <div className="flex flex-col gap-3">
            {result.hits.map((hit, i) => (
              <ResultCard
                key={hit.event_id}
                hit={hit}
                rank={i + 1}
                onViewEvent={setSelectedEventId}
              />
            ))}
          </div>
        )}

        {/* Placeholder when no search yet */}
        {!isLoading && !result && !error && (
          <div className="flex-1 flex items-center justify-center">
            <p className="text-sm text-txt-faint font-mono">
              enter a query to search events
            </p>
          </div>
        )}
      </main>

      {/* Source event drilldown modal */}
      {selectedEventId && (
        <EventModal
          eventId={selectedEventId}
          onClose={() => setSelectedEventId(null)}
        />
      )}
    </div>
  );
}

function _hasFilters(f: SearchFilters): boolean {
  return !!(
    (f.source_kind?.length ?? 0) > 0 ||
    (f.entity_type?.length ?? 0) > 0 ||
    f.after ||
    f.before
  );
}
