import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { Graph } from '../pages/Graph';
import * as graphApi from '../api/graph';
import type { GraphResponse } from '../types';

const MOCK_DATA: GraphResponse = {
  view: 'resolved',
  nodes: [
    {
      id: 'eid:1',
      node_type: 'Decision',
      label: 'Deprecate legacy-auth',
      status: 'active',
      source_event_ids: ['evt-001'],
      canonical_id: 'D-0006',
    },
    {
      id: 'eid:2',
      node_type: 'Service',
      label: 'payments-api',
      status: 'active',
      source_event_ids: ['evt-002'],
      canonical_id: 'payments-api',
    },
  ],
  edges: [
    {
      id: 'eid:e1',
      source: 'eid:1',
      target: 'eid:2',
      edge_type: 'DEPRECATES',
      is_merge_into: false,
      confidence: null,
      source_event_id: null,
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

describe('Graph', () => {
  beforeEach(() => {
    vi.spyOn(graphApi, 'fetchGraph').mockResolvedValue(MOCK_DATA);
  });

  it('renders the sidebar with view toggle', async () => {
    render(<Graph />, { wrapper });
    expect(await screen.findByText('resolved')).toBeInTheDocument();
    expect(screen.getByText('fragmented')).toBeInTheDocument();
  });

  it('shows node count after data loads', async () => {
    render(<Graph />, { wrapper });
    // Sidebar shows "Nodes" count
    expect(await screen.findByText('Nodes')).toBeInTheDocument();
  });

  it('switches to fragmented view on toggle click', async () => {
    render(<Graph />, { wrapper });
    const fragButton = await screen.findByRole('button', { name: /fragmented/i });
    fireEvent.click(fragButton);
    // fetchGraph should be called with 'fragmented'
    expect(graphApi.fetchGraph).toHaveBeenCalledWith('fragmented');
  });

  it('shows informational text for fragmented view', async () => {
    render(<Graph />, { wrapper });
    const fragButton = await screen.findByRole('button', { name: /fragmented/i });
    fireEvent.click(fragButton);
    expect(await screen.findByText(/MERGE_INTO edges/i)).toBeInTheDocument();
  });
});
