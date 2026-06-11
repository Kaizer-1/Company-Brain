/**
 * Phase 5A — /ingest page tests: form render + submit, reconciliation render, and error
 * handling (including the 503 busy case). The API client is mocked so no network is hit.
 */

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Ingest } from '../pages/Ingest';
import { ingestEvent } from '../api/ingest';
import { ApiError } from '../api/client';
import type { IngestEventResponse } from '../types';

vi.mock('../api/ingest', () => ({ ingestEvent: vi.fn() }));
const mockIngest = vi.mocked(ingestEvent);

function renderPage() {
  return render(
    <MemoryRouter>
      <Ingest />
    </MemoryRouter>,
  );
}

const RECONCILED: IngestEventResponse = {
  event_id: '11111111-1111-1111-1111-111111111111',
  status: 'reconciled',
  stages_run: [
    { name: 'extract', status: 'ok', duration_ms: 1200, detail: '1 nodes, 0 edges' },
    { name: 'contradiction', status: 'skipped', duration_ms: 0, detail: 'nothing to compare' },
  ],
  nodes_created: [{ id: 'nadia-okafor', label: 'Person', display_name: 'Nadia Okafor' }],
  nodes_merged: [],
  edges_created: [],
  contradictions_detected: [],
  duration_ms: 2300,
  cost_usd: 0.0031,
  deduplicated: false,
};

afterEach(() => vi.clearAllMocks());

async function fillAndSubmit() {
  const user = userEvent.setup();
  await user.type(
    screen.getByLabelText(/Event content/i),
    'welcome aboard Nadia Okafor, joining as a Software Engineer',
  );
  await user.click(screen.getByRole('button', { name: /Reconcile/i }));
  return user;
}

describe('Ingest page', () => {
  it('renders the form', () => {
    renderPage();
    expect(screen.getByLabelText(/Event content/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Reconcile/i })).toBeInTheDocument();
  });

  it('submits and renders the reconciliation result', async () => {
    mockIngest.mockResolvedValueOnce(RECONCILED);
    renderPage();
    await fillAndSubmit();

    await waitFor(() => expect(screen.getByText(/Reconciled in 2.3s/i)).toBeInTheDocument());
    expect(mockIngest).toHaveBeenCalledOnce();
    expect(screen.getByText(/Person · Nadia Okafor/i)).toBeInTheDocument();
    expect(screen.getByText(/View in graph/i)).toBeInTheDocument();
  });

  it('shows a friendly message on a 503 busy response', async () => {
    mockIngest.mockRejectedValueOnce(new ApiError(503, 'busy'));
    renderPage();
    await fillAndSubmit();

    await waitFor(() => expect(screen.getByText(/Ingestion is busy/i)).toBeInTheDocument());
  });

  it('renders the deduplicated banner', async () => {
    mockIngest.mockResolvedValueOnce({ ...RECONCILED, deduplicated: true });
    renderPage();
    await fillAndSubmit();

    await waitFor(() => expect(screen.getByText(/Already ingested/i)).toBeInTheDocument());
  });
});
