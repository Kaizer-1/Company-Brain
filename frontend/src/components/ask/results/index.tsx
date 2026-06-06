/**
 * Dispatches a structural tool's raw output to the matching renderer (Phase 4C).
 *
 * The four structural routes carry their QueryResult envelope as `tool_output`; this picks
 * the right card by route and unwraps `tool_output.value`. Returns null for non-structural
 * routes or missing output, so the caller can render it unconditionally beneath the NL answer.
 */

import type { AgentRoute, ToolOutput } from '../../../types';
import type {
  AggregateResult as AggregateResultData,
  EnumerateResult as EnumerateResultData,
  EntityResult as EntityResultData,
  NeighborsResult as NeighborsResultData,
} from '../../../types';
import { AggregateResult } from './AggregateResult';
import { EnumerateResult } from './EnumerateResult';
import { EntityResult } from './EntityResult';
import { NeighborsResult } from './NeighborsResult';

interface Props {
  route: AgentRoute;
  toolOutput?: ToolOutput | null;
}

export function StructuralResultView({ route, toolOutput }: Props) {
  const value = toolOutput?.value;
  if (!value) return null;

  switch (route) {
    case 'get_entity':
      return <EntityResult data={value as EntityResultData} />;
    case 'neighbors':
      return <NeighborsResult data={value as NeighborsResultData} />;
    case 'enumerate':
      return <EnumerateResult data={value as EnumerateResultData} />;
    case 'aggregate':
      return <AggregateResult data={value as AggregateResultData} />;
    default:
      return null;
  }
}

export { AggregateResult, EnumerateResult, EntityResult, NeighborsResult };
