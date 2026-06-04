import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { Queries } from '../pages/Queries';
import * as queriesApi from '../api/queries';
import type { QueryResult, ChainOwnerAnswer } from '../types';

const MOCK_KQ1: QueryResult<ChainOwnerAnswer> = {
  value: {
    decision_id: 'D-0006',
    decision_title: 'Deprecate legacy-auth',
    deprecated_systems: ['legacy-auth'],
    owner_people: ['diego-ramirez'],
    chains: [
      {
        deprecated_system: 'legacy-auth',
        dependent_service: 'payments-api',
        owner_type: 'Person',
        owner_id: 'diego-ramirez',
        person_id: 'diego-ramirez',
        person_display_name: 'Diego Ramirez',
        nodes: ['D-0006', 'legacy-auth', 'payments-api', 'diego-ramirez'],
      },
    ],
  },
  provenance: {
    by_element: { 'edge:D-0006->legacy-auth': ['evt-001'] },
    all_event_ids: ['evt-001'],
  },
};

// MemoryRouter without Routes: just provides location context so useSearchParams works.
// The Queries component doesn't need a matched route to render — the URL is just
// used for ?kq= search params which default to 'kq1' when absent.
function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/queries']}>
        {children}
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('Queries', () => {
  beforeEach(() => {
    vi.spyOn(queriesApi, 'fetchKq1').mockResolvedValue(MOCK_KQ1);
  });

  it('renders all four KQ options in the sidebar', () => {
    render(<Queries />, { wrapper });
    expect(screen.getByText(/KQ1 — Multi-hop ownership/i)).toBeInTheDocument();
    expect(screen.getByText(/KQ2 — Temporal contradiction/i)).toBeInTheDocument();
    expect(screen.getByText(/KQ3 — Blast radius/i)).toBeInTheDocument();
    expect(screen.getByText(/KQ4 — Change tracking/i)).toBeInTheDocument();
  });

  it('renders the Run query button', () => {
    render(<Queries />, { wrapper });
    expect(screen.getByRole('button', { name: /run query/i })).toBeInTheDocument();
  });

  it('fires the KQ1 API call when Run query is clicked', async () => {
    render(<Queries />, { wrapper });
    const runBtn = screen.getByRole('button', { name: /run query/i });
    fireEvent.click(runBtn);
    await waitFor(() => {
      expect(queriesApi.fetchKq1).toHaveBeenCalledWith('D-0006');
    });
  });

  it('displays the owner answer after KQ1 runs', async () => {
    render(<Queries />, { wrapper });
    fireEvent.click(screen.getByRole('button', { name: /run query/i }));
    // 'diego-ramirez' appears in both the answer headline and the chain viz
    const matches = await screen.findAllByText('diego-ramirez');
    expect(matches.length).toBeGreaterThan(0);
  });

  it('shows the provenance chain nodes', async () => {
    render(<Queries />, { wrapper });
    fireEvent.click(screen.getByRole('button', { name: /run query/i }));
    // Chain nodes may appear multiple times (answer + chain viz)
    const d6 = await screen.findAllByText('D-0006');
    expect(d6.length).toBeGreaterThan(0);
    const la = await screen.findAllByText('legacy-auth');
    expect(la.length).toBeGreaterThan(0);
  });

  it('has a collapsible source events section', async () => {
    render(<Queries />, { wrapper });
    fireEvent.click(screen.getByRole('button', { name: /run query/i }));
    const provenanceBtn = await screen.findByText(/source events/i);
    expect(provenanceBtn).toBeInTheDocument();
  });
});
