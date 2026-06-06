/**
 * SSE client for POST /api/ask/stream.
 *
 * Uses fetch + ReadableStream reader instead of EventSource because the browser's
 * native EventSource API only supports GET requests — it cannot send a POST body.
 * (See ADR 0026 for the full protocol rationale.)
 *
 * Yields typed StreamEvent objects parsed from the SSE wire format:
 *   event: <type>\n
 *   data: <json>\n
 *   \n
 *
 * Accepts an optional AbortSignal so the caller can cancel mid-stream (e.g. when
 * the user submits a new question before the previous one finishes).
 */

import { API_BASE } from './client';
import type { StreamEvent } from '../types';

export async function* streamAsk(
  question: string,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const response = await fetch(`${API_BASE}/api/ask/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
    signal,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json() as { detail?: string };
      detail = body.detail ?? detail;
    } catch { /* ignore */ }
    throw new Error(`API ${response.status}: ${detail}`);
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE frames are separated by double newlines.
      const frames = buffer.split('\n\n');
      buffer = frames.pop() ?? '';

      for (const frame of frames) {
        if (!frame.trim()) continue;

        let eventType = '';
        let dataLine = '';

        for (const line of frame.split('\n')) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            dataLine = line.slice(6);
          }
        }

        if (!eventType || !dataLine) continue;

        try {
          const data = JSON.parse(dataLine) as Record<string, unknown>;
          yield { type: eventType, ...data } as StreamEvent;
        } catch {
          // malformed JSON in a frame — skip it
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
