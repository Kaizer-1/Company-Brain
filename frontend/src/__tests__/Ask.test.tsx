import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { Ask } from '../pages/Ask';
import * as askApi from '../api/ask';
import type { AskResponse } from '../types';

const MOCK_RESPONSE: AskResponse = {
  answer: 'The payments-api is owned by the Payments Team [evt:evt-abc].',
  citations: [
    { event_id: 'evt-abc', source_kind: 'doc', source_ref: 'adr/D-0006', snippet: 'Payments Team owns payments-api.' },
  ],
  route: 'kq1',
  confidence: 'high',
  timings_ms: { classify_route: 120, kq1_owner: 30, synthesize_answer: 400, total: 560 },
  error: null,
  debug: {
    question: 'who owns payments-api?',
    route: 'kq1',
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
  },
};

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
    vi.spyOn(askApi, 'runAsk').mockResolvedValue(MOCK_RESPONSE);
  });

  it('renders the question input and Ask button', () => {
    render(<Ask />, { wrapper });
    expect(screen.getByPlaceholderText(/Ask anything about the company graph/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /ask/i })).toBeInTheDocument();
  });

  it('calls runAsk with debug=true on submit', async () => {
    render(<Ask />, { wrapper });
    fireEvent.change(screen.getByPlaceholderText(/Ask anything/i), {
      target: { value: 'who owns payments-api?' },
    });
    fireEvent.click(screen.getByRole('button', { name: /ask/i }));
    await waitFor(() => {
      expect(askApi.runAsk).toHaveBeenCalledWith('who owns payments-api?', true);
    });
  });

  it('renders the route badge and answer after asking', async () => {
    render(<Ask />, { wrapper });
    fireEvent.change(screen.getByPlaceholderText(/Ask anything/i), {
      target: { value: 'who owns payments-api?' },
    });
    fireEvent.click(screen.getByRole('button', { name: /ask/i }));
    expect((await screen.findAllByText(/KQ1 — Multi-hop ownership/i)).length).toBeGreaterThan(0);
    expect(screen.getByText(/owned by the Payments Team/i)).toBeInTheDocument();
  });

  it('renders the numbered Sources list', async () => {
    render(<Ask />, { wrapper });
    fireEvent.change(screen.getByPlaceholderText(/Ask anything/i), {
      target: { value: 'who owns payments-api?' },
    });
    fireEvent.click(screen.getByRole('button', { name: /ask/i }));
    expect(await screen.findByText('Sources')).toBeInTheDocument();
    expect(screen.getByText('adr/D-0006')).toBeInTheDocument();
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
