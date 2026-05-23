"use client";

/**
 * useMetacognition — exposes the agent's self-rated confidence per
 * assistant message.
 *
 * The Orqest framework emits a typed `metacognition.confidence` event
 * after every tool call that returns an `EnrichedOutput` — payload
 * fields: `confidence` (0..1 or null), `capability_boundary` (bool),
 * `uncertainty_targets` (string[]), `protocol` (string),
 * `duration_ms` (float). Events fire **per tool call**, not per
 * assistant message; this hook bridges the two by snapshotting the
 * latest event seen during a streaming window onto the message id when
 * the chat status returns to `"ready"` (i.e. the assistant turn just
 * closed).
 *
 * Returns `getMetaForMessage(messageId)` so the per-message badge can
 * read its frozen confidence without re-rendering on every event.
 */
import { useCallback, useMemo, useRef, useState } from "react";

import type { AgentEvent } from "@/lib/events";

import { useSidecar } from "./useSidecar";

export interface MetacognitionFrame {
  /** 0..1 confidence the agent self-rated. `null` when the protocol
   *  could not extract a value (e.g. tool returned a non-EnrichedOutput). */
  confidence: number | null;
  /** Free-form natural-language tags identifying *what* the agent is
   *  uncertain about (`["rate limits", "dataset shape"]`). */
  uncertainty_targets: string[];
  /** True when the agent flagged the task as outside its capability
   *  boundary — a strong "don't trust this without verification" signal. */
  capability_boundary: boolean;
  /** Which `ConfidenceProtocol` produced the value
   *  (`"structured_output"` / `"llm_self_rating"` / `"ensemble"`). */
  protocol: string | null;
  /** ISO timestamp from the originating event — useful for tooltips. */
  observed_at: string;
}

interface UseMetacognitionResult {
  /** Read the frozen metacognition frame for `messageId`, or `null` if
   *  the message never had a confidence event in its window. */
  getMetaForMessage: (messageId: string) => MetacognitionFrame | null;
}

/**
 * Build the hook for a session. ``currentMessageId`` is the most
 * recent assistant message's id (passed in from the chat hook). When
 * a `metacognition.confidence` event arrives, the hook attributes it
 * to whatever id the ref points at AT THAT MOMENT. ``chatStatus`` is
 * accepted for back-compat but no longer drives the freeze — the
 * earlier status-transition pattern fired BEFORE the post-turn
 * self-rating event arrived (the event was emitted from the chat
 * router's `on_complete`, which runs *after* the SDK transitions to
 * `"ready"`), so the badge never showed up.
 */
export function useMetacognition(
  sessionId: string,
  currentMessageId: string | null,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  _chatStatus: string,
): UseMetacognitionResult {
  // Per-message frozen frames. Once frozen, they don't change — the
  // badge reads from here.
  const [frames, setFrames] = useState<Map<string, MetacognitionFrame>>(
    () => new Map(),
  );

  // Ref so the SSE handler closure always reads the latest assistant
  // message id without re-subscribing on every render.
  const currentIdRef = useRef<string | null>(currentMessageId);
  currentIdRef.current = currentMessageId;

  useSidecar(sessionId, (evt: AgentEvent) => {
    if (evt.event_type !== "metacognition.confidence") return;
    const targetId = currentIdRef.current;
    if (!targetId) return;
    const data = evt.data as Partial<MetacognitionFrame> & {
      confidence?: number | null;
    };
    const frame: MetacognitionFrame = {
      confidence:
        typeof data.confidence === "number" ? data.confidence : null,
      uncertainty_targets: Array.isArray(data.uncertainty_targets)
        ? data.uncertainty_targets.filter(
            (s): s is string => typeof s === "string",
          )
        : [],
      capability_boundary: Boolean(data.capability_boundary),
      protocol:
        typeof data.protocol === "string" ? data.protocol : null,
      observed_at:
        typeof evt.timestamp === "string"
          ? evt.timestamp
          : new Date().toISOString(),
    };
    setFrames((prev) => {
      // First-write-wins: once a turn's confidence is frozen, later
      // re-emissions for the same id are dropped.
      if (prev.has(targetId)) return prev;
      const next = new Map(prev);
      next.set(targetId, frame);
      return next;
    });
  });

  const getMetaForMessage = useCallback(
    (messageId: string): MetacognitionFrame | null => {
      return frames.get(messageId) ?? null;
    },
    [frames],
  );

  return useMemo(() => ({ getMetaForMessage }), [getMetaForMessage]);
}
