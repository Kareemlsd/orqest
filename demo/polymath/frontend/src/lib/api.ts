/**
 * Tiny typed fetch wrapper targeting the Polymath backend.
 *
 * All calls go through the Next.js rewrite at `/api/backend/*` (defined in
 * next.config.ts), which proxies to `polymath-backend:8000` in docker-compose
 * and `localhost:8000` in local dev. A direct origin can be forced via
 * NEXT_PUBLIC_BACKEND_URL for testing.
 */

const DEFAULT_BASE = "/api/backend";

export function backendBase(): string {
  return process.env.NEXT_PUBLIC_BACKEND_URL?.replace(/\/$/, "") ?? DEFAULT_BASE;
}

export async function apiFetch<T = unknown>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${backendBase()}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    throw new Error(`Backend ${res.status}: ${await res.text().catch(() => res.statusText)}`);
  }
  return (await res.json()) as T;
}

export interface SessionSummary {
  id: string;
  title: string;
  created_at: string;
}

export async function createSession(title?: string): Promise<SessionSummary> {
  return apiFetch<SessionSummary>("/sessions", {
    method: "POST",
    body: JSON.stringify({ title: title ?? "New session" }),
  });
}
