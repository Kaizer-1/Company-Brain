import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { Audit } from '../pages/Audit';
import * as auditApi from '../api/audit';
import type { IngestionRunPage, MergeDecisionPage, SystemMetrics } from '../types';

const MOCK_DECISIONS: MergeDecisionPage = {
  total: 1,
  limit: 50,
  offset: 0,
  items: [
    {
      id: 'd-1',
      source_node_id: 'alice-chen',
      target_node_id: 'alice.chen',
      node_type: 'Person',
      decision: 'llm_merge',
      tier: 2,
      embedding_similarity: 0.92,
      rules_matched: [],
      llm_reasoning: 'Same person.',
      llm_model: 'claude-3.5-haiku',
      created_at: '2026-06-01T10:00:00Z',
    },
  ],
};

const MOCK_RUNS: IngestionRunPage = {
  next_cursor: null,
  items: [
    {
      id: 'run-1',
      event_id: 'feedface-0000-1111-2222-333344445555',
      source_kind: 'slack_message',
      content_snippet: 'New hire @nadia',
      status: 'reconciled',
      stages: [{ name: 'extract', status: 'ok', duration_ms: 3800, detail: '1 node' }],
      nodes_created_count: 1,
      nodes_merged_count: 0,
      edges_created_count: 0,
      contradictions_count: 0,
      cost_usd: 0.0031,
      duration_ms: 8200,
      started_at: '2026-06-10T19:23:50Z',
      completed_at: '2026-06-10T19:23:58Z',
      error: null,
    },
  ],
};

const MOCK_METRICS: SystemMetrics = {
  ingestion: {
    total: 3,
    by_status: { reconciled: 3 },
    duration_ms: { p50: 5800, p95: 12000, max: 15200 },
    cost_usd: { mean: 0.0031, p95: 0.0048, total: 0.0093 },
  },
  stages: {},
  adjudications: { resolution_total: 0, resolution_by_tier: {}, contradiction_total: 0 },
};

function wrapper(initialEntry: string) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return (
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[initialEntry]}>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  };
}

describe('Audit tabs', () => {
  beforeEach(() => {
    vi.spyOn(auditApi, 'fetchAudit').mockResolvedValue(MOCK_DECISIONS);
    vi.spyOn(auditApi, 'fetchIngestionRuns').mockResolvedValue(MOCK_RUNS);
    vi.spyOn(auditApi, 'fetchSystemMetrics').mockResolvedValue(MOCK_METRICS);
  });

  it('defaults to the Resolution decisions tab', async () => {
    render(<Audit />, { wrapper: wrapper('/audit') });
    expect(
      await screen.findByRole('heading', { name: /resolution audit trail/i }),
    ).toBeInTheDocument();
    expect(auditApi.fetchAudit).toHaveBeenCalled();
  });

  it('switches to the Ingestion runs tab on click', async () => {
    render(<Audit />, { wrapper: wrapper('/audit') });
    await screen.findByRole('heading', { name: /resolution audit trail/i });

    fireEvent.click(screen.getByRole('tab', { name: /ingestion runs/i }));

    expect(
      await screen.findByRole('heading', { name: /ingestion runs/i }),
    ).toBeInTheDocument();
    expect(auditApi.fetchIngestionRuns).toHaveBeenCalled();
    // event id from the runs feed is shown (truncated)
    expect(await screen.findByText('feedface')).toBeInTheDocument();
  });

  it('opens directly on the Ingestion runs tab from ?tab=ingestion-runs', async () => {
    render(<Audit />, { wrapper: wrapper('/audit?tab=ingestion-runs') });
    expect(
      await screen.findByRole('heading', { name: /ingestion runs/i }),
    ).toBeInTheDocument();
  });
});
