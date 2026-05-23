"use client";

/**
 * useChatMetrics — exposes per-message turn metrics emitted by Stream 1's
 * `chat.turn.completed` SSE event.
 *
 * The backend's `ModelResponse.id` (from pydantic-ai) does NOT match the
 * frontend's AI-SDK `UIMessage.id`. Earlier the hook tried to key by
 * the backend id and the join always missed, so the metadata strip
 * never rendered. The hook now ignores the backend id entirely and
 * attributes each incoming event to the **current assistant message
 * id** at event-receive time (passed in by the caller, captured in a
 * ref so the closure always sees the latest value).
 *
 * Mirror of `useMetacognition`'s shape (per-message frozen state +
 * `getMetricsForMessage(id)` accessor) so the call site in `Message.tsx`
 * reads symmetrically with the existing confidence frame access.
 */
import { useCallback, useMemo, useRef, useState } from "react";

import type { AgentEvent } from "@/lib/events";

import { useSidecar } from "./useSidecar";

export interface ChatTurnMetrics {
  /** Wall-clock time the assistant spent producing the turn. */
  durationMs: number;
  /** Number of tool invocations made during the turn. */
  toolCalls: number;
  /** Tokens consumed (prompt side, including cache reads). */
  inputTokens: number;
  /** Tokens generated (completion side). */
  outputTokens: number;
  /** Sum of input + output (backend authoritative). */
  totalTokens: number;
}

interface UseChatMetricsResult {
  /** Read the frozen metrics for `messageId`, or `null` if no
   *  `chat.turn.completed` event has been seen for that message. */
  getMetricsForMessage: (messageId: string) => ChatTurnMetrics | null;
}

interface BackendTurnPayload {
  duration_ms?: unknown;
  tool_calls?: unknown;
  input_tokens?: unknown;
  output_tokens?: unknown;
  total_tokens?: unknown;
}

function numeric(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}

/**
 * Build the hook for a session. ``currentAssistantId`` is the id of the
 * most recent assistant message in the chat transcript; the caller
 * (typically `ChatPane`) computes it from `useChat().messages`. Each
 * incoming `chat.turn.completed` event freezes its metrics onto
 * whatever id the ref points at *at event-receive time* — which
 * resolves the SDK-id-vs-pydantic-id mismatch without requiring a
 * shared id.
 */
export function useChatMetrics(
  sessionId: string,
  currentAssistantId: string | null,
): UseChatMetricsResult {
  // Per-message frozen metrics. Once a message id has metrics, they
  // don't change — historical turns are immutable, the strip reads from
  // here without caring about subsequent events.
  const [frames, setFrames] = useState<Map<string, ChatTurnMetrics>>(
    () => new Map(),
  );

  // Ref so the SSE handler closure always reads the latest id without
  // having to re-subscribe whenever the assistant message id rotates.
  const currentIdRef = useRef<string | null>(currentAssistantId);
  currentIdRef.current = currentAssistantId;

  useSidecar(sessionId, (evt: AgentEvent) => {
    if (evt.event_type !== "chat.turn.completed") return;
    const targetId = currentIdRef.current;
    if (!targetId) return;
    const data = evt.data as BackendTurnPayload;
    const metrics: ChatTurnMetrics = {
      durationMs: numeric(data.duration_ms),
      toolCalls: numeric(data.tool_calls),
      inputTokens: numeric(data.input_tokens),
      outputTokens: numeric(data.output_tokens),
      totalTokens: numeric(data.total_tokens),
    };
    setFrames((prev) => {
      // First-write-wins: a message's metrics are frozen at first
      // event arrival. Subsequent re-emissions for the same id are
      // dropped to keep historical numbers stable.
      if (prev.has(targetId)) return prev;
      const next = new Map(prev);
      next.set(targetId, metrics);
      return next;
    });
  });

  const getMetricsForMessage = useCallback(
    (messageId: string): ChatTurnMetrics | null => {
      return frames.get(messageId) ?? null;
    },
    [frames],
  );

  return useMemo(() => ({ getMetricsForMessage }), [getMetricsForMessage]);
}
