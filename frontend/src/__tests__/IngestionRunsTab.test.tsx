import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { IngestionRunsTab } from '../components/audit/IngestionRunsTab';
import * as auditApi from '../api/audit';
import type { IngestionRunPage, SystemMetrics } from '../types';

const MOCK_RUNS: IngestionRunPage = {
  next_cursor: null,
  items: [
    {
      id: 'run-1',
      event_id: 'abcdef12-3456-7890-abcd-ef1234567890',
      source_kind: 'slack_message',
      content_snippet: 'New intern @nadia joined the platform team',
      status: 'reconciled',
      stages: [
        { name: 'extract', status: 'ok', duration_ms: 3800, detail: '1 nodes' },
        { name: 'resolve', status: 'ok', duration_ms: 4200, detail: 'types=[Person]' },
        { name: 'consolidate', status: 'skipped', duration_ms: 0, detail: 'no Decision' },
      ],
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
    {
      id: 'run-2',
      event_id: '99999999-0000-1111-2222-333344445555',
      source_kind: 'doc',
      content_snippet: 'Decision: deprecate legacy-auth in favour of auth-service',
      status: 'partial',
      stages: [{ name: 'extract', status: 'failed', duration_ms: 120, detail: 'error' }],
      nodes_created_count: 0,
      nodes_merged_count: 0,
      edges_created_count: 0,
      contradictions_count: 0,
      cost_usd: 0,
      duration_ms: 450,
      started_at: '2026-06-10T18:00:00Z',
      completed_at: '2026-06-10T18:00:01Z',
      error: 'extraction failed',
    },
  ],
};

const MOCK_METRICS: SystemMetrics = {
  ingestion: {
    total: 7,
    by_status: { reconciled: 6, partial: 1, failed: 0 },
    duration_ms: { p50: 5800, p95: 12000, max: 15200 },
    cost_usd: { mean: 0.0031, p95: 0.0048, total: 0.0217 },
  },
  stages: {
    extract: { count: 7, duration_ms: { p50: 850, p95: 1400, max: 1600 } },
    resolve: { count: 7, duration_ms: { p50: 1200, p95: 9800, max: 15000 } },
  },
  adjudications: {
    resolution_total: 26,
    resolution_by_tier: { '1': 2, '2': 13, '3': 11 },
    contradiction_total: 4,
  },
};

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe('IngestionRunsTab', () => {
  beforeEach(() => {
    vi.spyOn(auditApi, 'fetchIngestionRuns').mockResolvedValue(MOCK_RUNS);
    vi.spyOn(auditApi, 'fetchSystemMetrics').mockResolvedValue(MOCK_METRICS);
  });

  it('renders the tab heading', async () => {
    render(<IngestionRunsTab />, { wrapper });
    expect(
      await screen.findByRole('heading', { name: /ingestion runs/i }),
    ).toBeInTheDocument();
  });

  it('renders a row per ingestion run with status and truncated event id', async () => {
    render(<IngestionRunsTab />, { wrapper });
    expect(await screen.findByText('reconciled')).toBeInTheDocument();
    expect(screen.getByText('partial')).toBeInTheDocument();
    // event id truncated to first 8 chars
    expect(screen.getByText('abcdef12')).toBeInTheDocument();
    // duration formatted to seconds
    expect(screen.getByText('8.2s')).toBeInTheDocument();
  });

  it('renders the System metrics strip from /api/metrics', async () => {
    render(<IngestionRunsTab />, { wrapper });
    expect(await screen.findByText(/system metrics/i)).toBeInTheDocument();
    // total ingestions (await — the metrics query resolves after the static heading)
    expect(await screen.findByText('7')).toBeInTheDocument();
    // resolution adjudication summary mentions the tier breakdown
    expect(await screen.findByText(/T2:13/)).toBeInTheDocument();
  });
});
