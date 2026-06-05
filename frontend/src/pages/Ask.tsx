/**
 * /ask — the agent page. The headline feature: ask a natural-language question, get a
 * grounded answer with clickable provenance.
 *
 * Single-column layout (not two-pane like /search) — the question is the focus. The agent
 * is always queried with debug=true so the "Show agent trace" disclosure can render the
 * route, reasoning, and per-node timings.
 */

import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';
import { runAsk } from '../api/ask';
import { AnswerView } from '../components/ask/AnswerView';
import { CitationList } from '../components/ask/CitationList';
import { AgentTrace } from '../components/ask/AgentTrace';
import { EventModal } from '../components/graph/EventModal';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { ErrorMessage } from '../components/ui/ErrorMessage';
import type { AskResponse } from '../types';

const ROUTE_LABELS: Record<string, string> = {
  kq1: 'KQ1 — Multi-hop ownership',
  kq2: 'KQ2 — Temporal contradiction',
  kq3: 'KQ3 — Blast radius',
  kq4: 'KQ4 — Change tracking',
  search: 'Semantic search',
  unknown: 'Out of scope',
};

// The pipeline stages, shown in order while a query is in flight.
const STAGES = ['Classifying route', 'Running query', 'Synthesizing answer'];

export function Ask() {
  const [question, setQuestion] = useState('');
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);

  const mutation = useMutation<AskResponse, Error, string>({
    mutationFn: (q: string) => runAsk(q, true),
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q) return;
    mutation.mutate(q);
  }

  const result = mutation.data;
  const isLoading = mutation.isPending;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto px-6 py-8 flex flex-col gap-6">
        {/* Question input — large but understated, not a hero */}
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit(e);
            }}
            placeholder="Ask anything about the company graph…  (e.g. who owns the service deprecated by D-0006?)"
            rows={3}
            className="w-full bg-s2 border border-border rounded px-4 py-3 text-sm text-txt placeholder:text-txt-faint focus:outline-none focus:border-accent/60 resize-none"
            autoFocus
          />
          <div className="flex items-center justify-between">
            <span className="font-mono text-2xs text-txt-faint">⌘↵ to ask</span>
            <Button type="submit" loading={isLoading} disabled={!question.trim()}>
              Ask
            </Button>
          </div>
        </form>

        <ErrorMessage error={mutation.error} />

        {/* In-flight skeleton showing pipeline stages */}
        {isLoading && (
          <div className="flex flex-col gap-2 text-sm text-txt-muted font-mono animate-pulse">
            {STAGES.map((s) => (
              <div key={s} className="flex items-center gap-2">
                <span className="text-accent">→</span> {s}…
              </div>
            ))}
          </div>
        )}

        {/* Answer */}
        {!isLoading && result && (
          <div className="flex flex-col gap-5">
            <div className="flex items-center gap-2">
              <Badge variant="accent">{ROUTE_LABELS[result.route] ?? result.route}</Badge>
              <span className="font-mono text-2xs text-txt-faint">
                confidence: {result.confidence}
              </span>
              {result.error && <Badge variant="warn">{result.error}</Badge>}
              <span className="font-mono text-2xs text-txt-faint ml-auto">
                {(result.timings_ms.total ?? 0).toFixed(0)}ms
              </span>
            </div>

            <AnswerView
              answer={result.answer}
              citations={result.citations}
              onCiteClick={setSelectedEventId}
            />

            <CitationList citations={result.citations} onSelect={setSelectedEventId} />

            {result.debug && <AgentTrace debug={result.debug} />}
          </div>
        )}

        {/* Initial placeholder */}
        {!isLoading && !result && !mutation.error && (
          <div className="text-sm text-txt-faint font-mono leading-relaxed">
            <p className="mb-2">Try one of:</p>
            <ul className="flex flex-col gap-1">
              <li>· Who owns the service that depends on the system deprecated by D-0006?</li>
              <li>· If payments-api fails, what is affected?</li>
              <li>· What changed about auth-service last quarter, and who approved it?</li>
              <li>· What do we know about the core-monolith migration?</li>
            </ul>
          </div>
        )}
      </div>

      {selectedEventId && (
        <EventModal eventId={selectedEventId} onClose={() => setSelectedEventId(null)} />
      )}
    </div>
  );
}
