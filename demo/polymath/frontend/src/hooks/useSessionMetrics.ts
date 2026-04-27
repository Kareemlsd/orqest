"use client";

/**
 * useSessionMetrics — feeds the chrome's header context ring.
 *
 * Mirrors `useMemory`'s REST hydrate + SSE live-merge pattern:
 *   - On mount: GET /sessions/{sid} and read `cumulative_usage`.
 *   - Subscribes to `chat.turn.completed` events; each payload carries a
 *     `cumulative` block — overwrite local state with those totals so we
 *     always reflect the backend's authoritative running tally (no
 *     incremental addition risk on retry / reconnect).
 *
 * Backend canonical shape (Stream 1):
 *   GET /sessions/{sid}.cumulative_usage = {
 *     input_tokens, output_tokens, total_tokens,
 *     cache_read_tokens, cache_write_tokens,
 *     tool_calls, turns, total_duration_ms
 *   }
 *
 * Returns the snake_case backend fields camel-cased for React-land
 * consumers, plus a `refresh()` callable for manual re-hydration if the
 * SSE stream gets out of sync.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { backendBase } from "@/lib/api";
import type { AgentEvent } from "@/lib/events";

import { useSidecar } from "./useSidecar";

export interface SessionMetrics {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  cacheReadTokens: number;
  cacheWriteTokens: number;
  toolCalls: number;
  turns: number;
  totalDurationMs: number;
}

export interface UseSessionMetricsResult extends SessionMetrics {
  refresh: () => Promise<void>;
}

const EMPTY_METRICS: SessionMetrics = {
  inputTokens: 0,
  outputTokens: 0,
  totalTokens: 0,
  cacheReadTokens: 0,
  cacheWriteTokens: 0,
  toolCalls: 0,
  turns: 0,
  totalDurationMs: 0,
};

interface BackendCumulativeUsage {
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  cache_read_tokens?: number;
  cache_write_tokens?: number;
  tool_calls?: number;
  turns?: number;
  total_duration_ms?: number;
}

interface BackendSessionResponse {
  cumulative_usage?: BackendCumulativeUsage;
}

function fromBackend(raw: BackendCumulativeUsage | undefined): SessionMetrics {
  if (!raw) return EMPTY_METRICS;
  return {
    inputTokens: numeric(raw.input_tokens),
    outputTokens: numeric(raw.output_tokens),
    totalTokens: numeric(raw.total_tokens),
    cacheReadTokens: numeric(raw.cache_read_tokens),
    cacheWriteTokens: numeric(raw.cache_write_tokens),
    toolCalls: numeric(raw.tool_calls),
    turns: numeric(raw.turns),
    totalDurationMs: numeric(raw.total_duration_ms),
  };
}

function numeric(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}

export function useSessionMetrics(sessionId: string): UseSessionMetricsResult {
  const [metrics, setMetrics] = useState<SessionMetrics>(EMPTY_METRICS);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    try {
      const resp = await fetch(`${backendBase()}/sessions/${sessionId}`);
      if (!resp.ok) return;
      const payload = (await resp.json()) as BackendSessionResponse;
      setMetrics(fromBackend(payload.cumulative_usage));
    } catch {
      // SSE will populate eventually; silent failure is fine.
    }
  }, [sessionId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useSidecar(sessionId, (evt: AgentEvent) => {
    if (evt.event_type !== "chat.turn.completed") return;
    const data = evt.data as { cumulative?: BackendCumulativeUsage };
    if (!data?.cumulative) return;
    setMetrics(fromBackend(data.cumulative));
  });

  return useMemo<UseSessionMetricsResult>(
    () => ({ ...metrics, refresh }),
    [metrics, refresh],
  );
}
