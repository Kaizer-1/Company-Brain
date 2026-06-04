/**
 * Base API client. All requests use the VITE_API_BASE env var (default: empty = same origin).
 * Returns typed JSON or throws a structured ApiError.
 */

export const API_BASE = import.meta.env.VITE_API_BASE ?? '';

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(`API ${status}: ${detail}`);
    this.name = 'ApiError';
  }
}

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: { Accept: 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      // ignore JSON parse failure — use statusText
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

// TanStack Query key factories — stable, colocated keys for consistent cache behaviour
export const queryKeys = {
  graph: (view: string) => ['graph', view] as const,
  event: (id: string) => ['event', id] as const,
  kq1: (decisionId: string) => ['kq1', decisionId] as const,
  kq2: (windowDays: number) => ['kq2', windowDays] as const,
  kq3: (service: string, maxDepth: number) => ['kq3', service, maxDepth] as const,
  kq4: (target: string, windowDays: number) => ['kq4', target, windowDays] as const,
  audit: (filters: Record<string, string | number | null>) => ['audit', filters] as const,
};
