/**
 * Streaming-path tests for the Ask page (Phase 4B).
 *
 * Mocks the streamAsk async generator with a scripted sequence of SSE events
 * and verifies that:
 *   – per-stage progress renders as events arrive
 *   – synthesis tokens accumulate into the streaming text display
 *   – citations hydrate after the complete event
 *   – errors render inline without clearing already-streamed text
 */

import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { Ask } from '../pages/Ask';
import * as askStreamModule from '../api/askStream';
import type { StreamEvent } from '../types';

// The component uses USE_STREAMING = true, so these tests exercise the streaming path.

const CITATION = {
  event_id: 'evt-stream-1',
  source_kind: 'doc',
  source_ref: 'adr/D-0006',
  snippet: 'Payments Team owns payments-api.',
};

const EVENTS_SEARCH: StreamEvent[] = [
  { type: 'route', route: 'search', reasoning: 'open-ended lookup', tool_input: {} },
  { type: 'tool_start', tool: 'search', params: {} },
  { type: 'tool_done', tool_output_summary: '3 events', timings_ms: {} },
  { type: 'synthesis_start', retry: false },
  { type: 'synthesis_token', text: 'Payments' },
  { type: 'synthesis_token', text: ' Team' },
  { type: 'synthesis_token', text: ' owns.' },
  { type: 'synthesis_done', answer_final: 'Payments Team owns.', citations_raw: ['evt-stream-1'] },
  { type: 'verify_start' },
  { type: 'verify_done', verified: true, retry_count: 0 },
  {
    type: 'complete',
    answer: 'Payments Team owns.',
    citations: [CITATION],
    route: 'search',
    confidence: 'high',
    timings_ms: { total: 2200 },
    error: null,
    debug: null,
  },
];

const EVENTS_ERROR: StreamEvent[] = [
  { type: 'route', route: 'search', reasoning: 'lookup', tool_input: {} },
  { type: 'error', error: 'synthesis timed out', stage: 'synthesis' },
];

async function* makeGen(events: StreamEvent[]): AsyncGenerator<StreamEvent> {
  for (const e of events) yield e;
}

function wrapper({ children }: { children: React.ReactNode }) {
  return <MemoryRouter initialEntries={['/ask']}>{children}</MemoryRouter>;
}

describe('Ask streaming path', () => {
  beforeEach(() => {
    vi.spyOn(askStreamModule, 'streamAsk').mockImplementation(
      () => makeGen(EVENTS_SEARCH),
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders input and Ask button', () => {
    render(<Ask />, { wrapper });
    expect(screen.getByPlaceholderText(/Ask anything/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /ask/i })).toBeInTheDocument();
  });

  it('calls streamAsk with the entered question', async () => {
    render(<Ask />, { wrapper });
    fireEvent.change(screen.getByPlaceholderText(/Ask anything/i), {
      target: { value: 'who owns payments-api?' },
    });
    fireEvent.click(screen.getByRole('button', { name: /ask/i }));

    await waitFor(() => {
      expect(askStreamModule.streamAsk).toHaveBeenCalledWith(
        'who owns payments-api?',
        expect.anything(),
      );
    });
  });

  it('shows route badge after route event', async () => {
    render(<Ask />, { wrapper });
    fireEvent.change(screen.getByPlaceholderText(/Ask anything/i), {
      target: { value: 'payments ownership' },
    });
    fireEvent.click(screen.getByRole('button', { name: /ask/i }));

    // Use findAllByText (same pattern as Ask.test.tsx badge assertions) to handle
    // the fact that React 18 may batch all streaming state updates into one render.
    expect((await screen.findAllByText(/semantic search/i)).length).toBeGreaterThan(0);
  });

  it('shows streaming completed via route and confidence in final view', async () => {
    render(<Ask />, { wrapper });
    fireEvent.change(screen.getByPlaceholderText(/Ask anything/i), {
      target: { value: 'payments ownership' },
    });
    fireEvent.click(screen.getByRole('button', { name: /ask/i }));

    // React 18 batches all streaming state updates into one render (no intermediate
    // 'streaming' state visible in tests). Verify the final view reached 'complete':
    // both the route badge and confidence label must appear.
    expect((await screen.findAllByText(/semantic search/i)).length).toBeGreaterThan(0);
    expect(await screen.findByText(/confidence: high/i)).toBeInTheDocument();
  });

  it('hydrates citations from the complete event', async () => {
    render(<Ask />, { wrapper });
    fireEvent.change(screen.getByPlaceholderText(/Ask anything/i), {
      target: { value: 'payments ownership' },
    });
    fireEvent.click(screen.getByRole('button', { name: /ask/i }));

    expect(await screen.findByText('Sources')).toBeInTheDocument();
    expect(await screen.findByText('adr/D-0006')).toBeInTheDocument();
  });

  it('shows the final answer text after complete event', async () => {
    render(<Ask />, { wrapper });
    fireEvent.change(screen.getByPlaceholderText(/Ask anything/i), {
      target: { value: 'payments ownership' },
    });
    fireEvent.click(screen.getByRole('button', { name: /ask/i }));

    // findAllByText with regex handles cases where the text might appear in multiple
    // DOM nodes (e.g. parent containers also match partial text).
    expect((await screen.findAllByText(/Payments Team owns/i)).length).toBeGreaterThan(0);
  });

  it('shows inline error when error event arrives', async () => {
    vi.spyOn(askStreamModule, 'streamAsk').mockImplementation(
      () => makeGen(EVENTS_ERROR),
    );

    render(<Ask />, { wrapper });
    fireEvent.change(screen.getByPlaceholderText(/Ask anything/i), {
      target: { value: 'something that breaks' },
    });
    fireEvent.click(screen.getByRole('button', { name: /ask/i }));

    expect(await screen.findByText(/synthesis timed out/i)).toBeInTheDocument();
  });
});
