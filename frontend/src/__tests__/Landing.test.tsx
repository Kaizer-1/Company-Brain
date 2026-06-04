import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { Landing } from '../pages/Landing';

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe('Landing', () => {
  it('renders the project title', () => {
    render(<Landing />, { wrapper });
    expect(screen.getByRole('heading', { name: /company brain/i })).toBeInTheDocument();
  });

  it('renders all four killer queries', () => {
    render(<Landing />, { wrapper });
    // Some terms appear in both the intro paragraph and the KQ notes — use getAllByText
    expect(screen.getAllByText(/multi-hop graph traversal/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/temporal contradiction/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/graph reachability/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/temporal edge traversal/i).length).toBeGreaterThan(0);
  });

  it('renders "Try it" links to /queries', () => {
    render(<Landing />, { wrapper });
    const tryLinks = screen.getAllByRole('link', { name: /try it/i });
    expect(tryLinks).toHaveLength(4);
    expect(tryLinks[0]).toHaveAttribute('href', '/queries?kq=kq1');
  });

  it('renders the graph navigation link', () => {
    render(<Landing />, { wrapper });
    const graphLink = screen.getByRole('link', { name: /browse the graph/i });
    expect(graphLink).toHaveAttribute('href', '/graph');
  });

  it('does not render gradient backgrounds or hero sections', () => {
    const { container } = render(<Landing />, { wrapper });
    const html = container.innerHTML;
    // Verify no gradient classes slipped in
    expect(html).not.toMatch(/bg-gradient|from-purple|to-pink/);
  });
});
