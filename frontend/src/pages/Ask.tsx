/**
 * /ask — the agent page. The headline feature: ask a natural-language question, get a
 * grounded answer with clickable provenance.
 *
 * Single-column layout (not two-pane like /search). When USE_STREAMING is true the page
 * uses POST /api/ask/stream and renders per-stage progress events as they arrive; set it
 * to false to fall back to the JSON endpoint (useful for debugging). The agent is always
 * queried with debug=true so the "Show agent trace" disclosure can render the full trace.
 */

import { useRef, useState } from 'react';
import { streamAsk } from '../api/askStream';
import { runAsk } from '../api/ask';
import { AnswerView } from '../components/ask/AnswerView';
import { CitationList } from '../components/ask/CitationList';
import { AgentTrace } from '../components/ask/AgentTrace';
import { StreamProgress } from '../components/ask/StreamProgress';
import { StructuralResultView } from '../components/ask/results';
import { EventModal } from '../components/graph/EventModal';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { ErrorMessage } from '../components/ui/ErrorMessage';
import type { AskResponse, StreamEvent, StreamEventComplete } from '../types';

// Flip to false to fall back to the JSON endpoint (no streaming).
const USE_STREAMING = true;

const ROUTE_LABELS: Record<string, string> = {
  kq1: 'KQ1 — Multi-hop ownership',
  kq2: 'KQ2 — Temporal contradiction',
  kq3: 'KQ3 — Blast radius',
  kq4: 'KQ4 — Change tracking',
  search: 'Semantic search',
  get_entity: 'Entity lookup',
  neighbors: 'Typed neighbors',
  enumerate: 'Enumeration',
  aggregate: 'Aggregation',
  unknown: 'Out of scope',
};

type StreamStatus = 'idle' | 'streaming' | 'complete' | 'error';

interface StreamState {
  status: StreamStatus;
  events: StreamEvent[];
  streamingText: string;
  result: StreamEventComplete | null;
  error: string | null;
}

const IDLE_STATE: StreamState = {
  status: 'idle',
  events: [],
  streamingText: '',
  result: null,
  error: null,
};

export function Ask() {
  const [question, setQuestion] = useState('');
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);

  // Non-streaming fallback state (used when USE_STREAMING = false)
  const [jsonResult, setJsonResult] = useState<AskResponse | null>(null);
  const [jsonError, setJsonError] = useState<Error | null>(null);
  const [jsonLoading, setJsonLoading] = useState(false);

  // Streaming state
  const [streamState, setStreamState] = useState<StreamState>(IDLE_STATE);
  const abortRef = useRef<AbortController | null>(null);

  async function handleStreamingSubmit(q: string) {
    // Cancel any in-flight stream
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    const { signal } = abortRef.current;

    setStreamState({ status: 'streaming', events: [], streamingText: '', result: null, error: null });

    try {
      for await (const event of streamAsk(q, signal)) {
        if (signal.aborted) break;

        setStreamState((prev) => {
          const newEvents = [...prev.events, event];
          let newText = prev.streamingText;

          // Reset text on retry synthesis pass
          if (event.type === 'synthesis_start' && event.retry) {
            newText = '';
          } else if (event.type === 'synthesis_token') {
            newText += event.text;
          }

          const patch: Partial<StreamState> = { events: newEvents, streamingText: newText };

          if (event.type === 'complete') {
            patch.status = 'complete';
            patch.result = event;
          } else if (event.type === 'error') {
            patch.status = 'error';
            patch.error = event.error;
          }

          return { ...prev, ...patch };
        });
      }
    } catch (err) {
      if ((err as { name?: string }).name === 'AbortError') return;
      setStreamState((prev) => ({
        ...prev,
        status: 'error',
        error: err instanceof Error ? err.message : 'Unknown error',
      }));
    }
  }

  async function handleJsonSubmit(q: string) {
    setJsonLoading(true);
    setJsonError(null);
    setJsonResult(null);
    try {
      const res = await runAsk(q, true);
      setJsonResult(res);
    } catch (err) {
      setJsonError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setJsonLoading(false);
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q) return;
    if (USE_STREAMING) {
      void handleStreamingSubmit(q);
    } else {
      void handleJsonSubmit(q);
    }
  }

  const isLoading = USE_STREAMING
    ? streamState.status === 'streaming'
    : jsonLoading;

  // Derive the final result for non-streaming path
  const jsonResultAsResponse: AskResponse | null = jsonResult;

  // Derive the final result for streaming path
  const streamComplete = streamState.result;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto px-6 py-8 flex flex-col gap-6">
        {/* Question input */}
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

        {/* Error for non-streaming path */}
        {!USE_STREAMING && <ErrorMessage error={jsonError} />}

        {/* Streaming error */}
        {USE_STREAMING && streamState.status === 'error' && streamState.error && (
          <p className="text-sm text-red-400 font-mono">{streamState.error}</p>
        )}

        {/* Streaming progress (shown while in flight) */}
        {USE_STREAMING && streamState.status === 'streaming' && (
          <StreamProgress events={streamState.events} streamingText={streamState.streamingText} />
        )}

        {/* Final streaming result */}
        {USE_STREAMING && streamState.status === 'complete' && streamComplete && (
          <div className="flex flex-col gap-5">
            <div className="flex items-center gap-2">
              <Badge variant="accent">{ROUTE_LABELS[streamComplete.route] ?? streamComplete.route}</Badge>
              <span className="font-mono text-2xs text-txt-faint">
                confidence: {streamComplete.confidence}
              </span>
              {streamComplete.error && <Badge variant="warn">{streamComplete.error}</Badge>}
              <span className="font-mono text-2xs text-txt-faint ml-auto">
                {(streamComplete.timings_ms.total ?? 0).toFixed(0)}ms
              </span>
            </div>

            <AnswerView
              answer={streamComplete.answer}
              citations={streamComplete.citations}
              onCiteClick={setSelectedEventId}
            />

            <StructuralResultView route={streamComplete.route} toolOutput={streamComplete.tool_output} />

            <CitationList citations={streamComplete.citations} onSelect={setSelectedEventId} />

            {streamComplete.debug && <AgentTrace debug={streamComplete.debug} />}
          </div>
        )}

        {/* Non-streaming in-flight skeleton */}
        {!USE_STREAMING && jsonLoading && (
          <div className="flex flex-col gap-2 text-sm text-txt-muted font-mono animate-pulse">
            {['Classifying route', 'Running query', 'Synthesizing answer'].map((s) => (
              <div key={s} className="flex items-center gap-2">
                <span className="text-accent">→</span> {s}…
              </div>
            ))}
          </div>
        )}

        {/* Non-streaming result */}
        {!USE_STREAMING && !jsonLoading && jsonResultAsResponse && (
          <div className="flex flex-col gap-5">
            <div className="flex items-center gap-2">
              <Badge variant="accent">{ROUTE_LABELS[jsonResultAsResponse.route] ?? jsonResultAsResponse.route}</Badge>
              <span className="font-mono text-2xs text-txt-faint">
                confidence: {jsonResultAsResponse.confidence}
              </span>
              {jsonResultAsResponse.error && <Badge variant="warn">{jsonResultAsResponse.error}</Badge>}
              <span className="font-mono text-2xs text-txt-faint ml-auto">
                {(jsonResultAsResponse.timings_ms.total ?? 0).toFixed(0)}ms
              </span>
            </div>

            <AnswerView
              answer={jsonResultAsResponse.answer}
              citations={jsonResultAsResponse.citations}
              onCiteClick={setSelectedEventId}
            />

            <StructuralResultView route={jsonResultAsResponse.route} toolOutput={jsonResultAsResponse.tool_output} />

            <CitationList citations={jsonResultAsResponse.citations} onSelect={setSelectedEventId} />

            {jsonResultAsResponse.debug && <AgentTrace debug={jsonResultAsResponse.debug} />}
          </div>
        )}

        {/* Initial placeholder */}
        {((USE_STREAMING && streamState.status === 'idle') ||
          (!USE_STREAMING && !jsonLoading && !jsonResultAsResponse && !jsonError)) && (
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
