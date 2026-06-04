import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { Audit } from '../pages/Audit';
import * as auditApi from '../api/audit';
import type { MergeDecisionPage } from '../types';

const MOCK_PAGE: MergeDecisionPage = {
  total: 3,
  limit: 50,
  offset: 0,
  items: [
    {
      id: 'uuid-1',
      source_node_id: 'alice-chen',
      target_node_id: 'alice.chen',
      node_type: 'Person',
      decision: 'llm_merge',
      tier: 2,
      embedding_similarity: 0.92,
      rules_matched: [],
      llm_reasoning: 'Both refer to the same person — same team, same email domain.',
      llm_model: 'claude-3.5-haiku',
      created_at: '2026-06-01T10:00:00Z',
    },
    {
      id: 'uuid-2',
      source_node_id: 'notifications-api',
      target_node_id: 'notification-worker',
      node_type: 'Service',
      decision: 'llm_no_merge',
      tier: 2,
      embedding_similarity: 0.73,
      rules_matched: [],
      llm_reasoning: 'Different services: one accepts requests, one processes jobs.',
      llm_model: 'claude-3.5-haiku',
      created_at: '2026-06-01T09:30:00Z',
    },
    {
      id: 'uuid-3',
      source_node_id: 'legacy-auth',
      target_node_id: 'legacy-auth',
      node_type: 'System',
      decision: 'auto_merge',
      tier: 1,
      embedding_similarity: null,
      rules_matched: ['exact_canonical_name'],
      llm_reasoning: null,
      llm_model: null,
      created_at: '2026-06-01T09:00:00Z',
    },
  ],
};

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe('Audit', () => {
  beforeEach(() => {
    vi.spyOn(auditApi, 'fetchAudit').mockResolvedValue(MOCK_PAGE);
  });

  it('renders the page heading', async () => {
    render(<Audit />, { wrapper });
    expect(await screen.findByRole('heading', { name: /resolution audit trail/i })).toBeInTheDocument();
  });

  it('renders all three mock rows', async () => {
    render(<Audit />, { wrapper });
    expect(await screen.findByText('alice-chen')).toBeInTheDocument();
    expect(screen.getByText('notifications-api')).toBeInTheDocument();
    // 'legacy-auth' appears in both source and target columns for the auto_merge row
    const legacyMatches = screen.getAllByText('legacy-auth');
    expect(legacyMatches.length).toBeGreaterThan(0);
  });

  it('shows decision badges with correct labels', async () => {
    render(<Audit />, { wrapper });
    expect(await screen.findByText('LLM merge')).toBeInTheDocument();
    expect(screen.getByText('LLM no merge')).toBeInTheDocument();
    expect(screen.getByText('auto merge')).toBeInTheDocument();
  });

  it('displays total count', async () => {
    render(<Audit />, { wrapper });
    expect(await screen.findByText('3 total')).toBeInTheDocument();
  });

  it('tier filter re-queries the API', async () => {
    render(<Audit />, { wrapper });
    await screen.findByText('alice-chen'); // wait for initial load
    const tierSelect = screen.getByLabelText ?
      screen.getByLabelText(/tier/i) :
      screen.getAllByRole('combobox')[0];
    fireEvent.change(tierSelect, { target: { value: '2' } });
    await waitFor(() => {
      expect(auditApi.fetchAudit).toHaveBeenCalledWith(
        expect.objectContaining({ tier: 2 }),
      );
    });
  });

  it('expands LLM reasoning on row click', async () => {
    render(<Audit />, { wrapper });
    // Multiple rows have reasoning — take the first Expand button
    const expandBtns = await screen.findAllByText('Expand');
    expect(expandBtns.length).toBeGreaterThan(0);
    fireEvent.click(expandBtns[0]);
    expect(await screen.findByText(/both refer to the same person/i)).toBeInTheDocument();
  });
});
