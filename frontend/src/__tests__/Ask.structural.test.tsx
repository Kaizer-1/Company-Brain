/**
 * Phase 4C — structural result renderer tests. One per renderer: given mock tool output,
 * the dispatcher renders the correct card with the expected data.
 */

import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { StructuralResultView } from '../components/ask/results';
import type {
  AggregateResult,
  EntityResult,
  EnumerateResult,
  NeighborsResult,
  ToolOutput,
} from '../types';

function renderView(route: Parameters<typeof StructuralResultView>[0]['route'], value: unknown) {
  const toolOutput = { value } as ToolOutput;
  return render(
    <MemoryRouter>
      <StructuralResultView route={route} toolOutput={toolOutput} />
    </MemoryRouter>,
  );
}

describe('StructuralResultView', () => {
  it('renders get_entity properties and edge summary', () => {
    const data: EntityResult = {
      entity_id: 'D-0006',
      node_type: 'Decision',
      properties: { title: 'Deprecate legacy-auth', status: 'active' },
      outgoing_edges: { DEPRECATES: 1, ABOUT: 2 },
      incoming_edges: {},
      source_event_ids: ['e1'],
    };
    renderView('get_entity', data);
    expect(screen.getByText('Decision')).toBeInTheDocument();
    expect(screen.getByText('Deprecate legacy-auth')).toBeInTheDocument();
    expect(screen.getByText(/DEPRECATES×1/)).toBeInTheDocument();
  });

  it('renders neighbors grouped by edge type', () => {
    const data: NeighborsResult = {
      entity_id: 'Payments',
      total_count: 2,
      neighbors: [
        { neighbor_id: 'alice-chen', neighbor_name: 'alice-chen', neighbor_type: 'Person', edge_type: 'MEMBER_OF', outgoing: false, source_event_id: 'm1' },
        { neighbor_id: 'bob', neighbor_name: 'bob', neighbor_type: 'Person', edge_type: 'MEMBER_OF', outgoing: false, source_event_id: 'm2' },
      ],
    };
    renderView('neighbors', data);
    expect(screen.getByText('MEMBER_OF')).toBeInTheDocument();
    expect(screen.getByText('alice-chen')).toBeInTheDocument();
    expect(screen.getByText('bob')).toBeInTheDocument();
  });

  it('renders enumerate list with total and truncation note', () => {
    const data: EnumerateResult = {
      node_type: 'Person',
      total_count: 13,
      returned_count: 2,
      nodes: [
        { id: 'alice-chen', name: 'alice-chen', status: 'active', extra_fields: { handle: '@alice' }, source_event_ids: ['e1'] },
        { id: 'bob', name: 'bob', status: 'active', extra_fields: {}, source_event_ids: ['e2'] },
      ],
      filters_applied: {},
    };
    renderView('enumerate', data);
    expect(screen.getByText(/showing 2 of 13/)).toBeInTheDocument();
    expect(screen.getByText('alice-chen')).toBeInTheDocument();
  });

  it('renders aggregate groups with counts', () => {
    const data: AggregateResult = {
      node_type: 'Service',
      total: 12,
      groups: [
        { group_name: 'Payments', group_type: 'Team', count: 4 },
        { group_name: 'Growth', group_type: 'Team', count: 3 },
      ],
    };
    renderView('aggregate', data);
    expect(screen.getByText(/total: 12/)).toBeInTheDocument();
    expect(screen.getByText('Payments')).toBeInTheDocument();
    expect(screen.getByText('4')).toBeInTheDocument();
  });
});
