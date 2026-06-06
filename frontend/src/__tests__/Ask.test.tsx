/**
 * Core Ask page tests — updated in Phase 4B to mock streamAsk (the default path)
 * rather than runAsk, since USE_STREAMING = true.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { Ask } from '../pages/Ask';
import * as askStreamModule from '../api/askStream';
import type { StreamEvent } from '../types';

// Build a complete streaming event that mirrors the old MOCK_RESPONSE shape.
const CITATION = {
  event_id: 'evt-abc',
  source_kind: 'doc',
  source_ref: 'adr/D-0006',
  snippet: 'Payments Team owns payments-api.',
};

const MOCK_DEBUG = {
  question: 'who owns payments-api?',
  route: 'kq1' as const,
  route_reasoning: 'decision -> deprecated system -> dependent service -> owner chain',
  tool_input: { decision_id: 'D-0006' },
  available_event_ids: ['evt-abc'],
  answer: 'The payments-api is owned by the Payments Team [evt:evt-abc].',
  citations: ['evt-abc'],
  verified: true,
  retry_count: 0,
  error: null,
  timings_ms: { classify_route: 120, kq1_owner: 30, synthesize_answer: 400, total: 560 },
  cost_usd: 0.0012,
};

const COMPLETE_EVENT: StreamEvent = {
  type: 'complete',
  answer: 'The payments-api is owned by the Payments Team [evt:evt-abc].',
  citations: [CITATION],
  route: 'kq1',
  confidence: 'high',
  timings_ms: { classify_route: 120, kq1_owner: 30, synthesize_answer: 400, total: 560 },
  error: null,
  debug: MOCK_DEBUG,
};

async function* makeGen(events: StreamEvent[]): AsyncGenerator<StreamEvent> {
  for (const e of events) yield e;
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/ask']}>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe('Ask', () => {
  beforeEach(() => {
    vi.spyOn(askStreamModule, 'streamAsk').mockImplementation(
      () => makeGen([COMPLETE_EVENT]),
    );
  });

  it('renders the question input and Ask button', () => {
    render(<Ask />, { wrapper });
    expect(screen.getByPlaceholderText(/Ask anything about the company graph/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /ask/i })).toBeInTheDocument();
  });

  it('calls streamAsk with the question on submit', async () => {
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

  it('renders the route badge and answer after asking', async () => {
    render(<Ask />, { wrapper });
    fireEvent.change(screen.getByPlaceholderText(/Ask anything/i), {
      target: { value: 'who owns payments-api?' },
    });
    fireEvent.click(screen.getByRole('button', { name: /ask/i }));
    expect((await screen.findAllByText(/KQ1 — Multi-hop ownership/i)).length).toBeGreaterThan(0);
    expect(await screen.findByText(/owned by the Payments Team/i)).toBeInTheDocument();
  });

  it('renders the numbered Sources list', async () => {
    render(<Ask />, { wrapper });
    fireEvent.change(screen.getByPlaceholderText(/Ask anything/i), {
      target: { value: 'who owns payments-api?' },
    });
    fireEvent.click(screen.getByRole('button', { name: /ask/i }));
    expect(await screen.findByText('Sources')).toBeInTheDocument();
    expect(await screen.findByText('adr/D-0006')).toBeInTheDocument();
  });

  it('exposes the agent trace disclosure', async () => {
    render(<Ask />, { wrapper });
    fireEvent.change(screen.getByPlaceholderText(/Ask anything/i), {
      target: { value: 'who owns payments-api?' },
    });
    fireEvent.click(screen.getByRole('button', { name: /ask/i }));
    expect(await screen.findByText(/Show agent trace/i)).toBeInTheDocument();
  });
});
