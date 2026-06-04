import type { EventDTO } from '../types';
import { apiFetch } from './client';

export function fetchEvent(eventId: string): Promise<EventDTO> {
  return apiFetch<EventDTO>(`/api/events/${encodeURIComponent(eventId)}`);
}
