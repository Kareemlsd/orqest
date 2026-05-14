"use client";

/**
 * useMetacognition — subscribe to `metacognition.confidence` events and
 * freeze each frame onto the current assistant message id.
 *
 * Critical id-keying note: backend ModelResponse.id does NOT match the
 * AI SDK's UIMessage.id. Do not key by backend id. Pass the frontend's
 * current assistant message id via `currentAssistantId`; the hook
 * captures it in a ref and pairs each arriving event to it (first-write
 * wins).
 *
 * USAGE:
 *
 *   const { messages, status } = useChat(...);
 *   const currentAssistantId = useMemo(
 *     () => messages.findLast(m => m.role === "assistant" && status === "streaming")?.id ?? null,
 *     [messages, status],
 *   );
 *   const { frames } = useMetacognition(sessionId, currentAssistantId);
 *
 *   // In the message list:
 *   const frame = frames.get(message.id);
 *   if (frame) <ConfidenceBadge confidence={frame.confidence} ... />
 */

import { useCallback, useRef, useState } from "react";

import type { AgentEvent } from "./events";
import { useSidecar } from "./useSidecar";

export interface ConfidenceFrame {
  confidence: number | null;
  uncertaintyTargets: string[];
  capabilityBoundary: boolean;
  protocol: string | null;
}

export function useMetacognition(
  sessionId: string,
  currentAssistantId: string | null,
) {
  const [frames, setFrames] = useState<Map<string, ConfidenceFrame>>(
    () => new Map(),
  );
  const currentIdRef = useRef(currentAssistantId);
  currentIdRef.current = currentAssistantId;

  const handler = useCallback((evt: AgentEvent) => {
    if (evt.event_type !== "metacognition.confidence") return;
    const targetId = currentIdRef.current;
    if (!targetId) return;
    setFrames((prev) => {
      // First-write-wins: ignore subsequent confidence events for the
      // same message (e.g. delayed arrivals after the agent moved on).
      if (prev.has(targetId)) return prev;
      const next = new Map(prev);
      next.set(targetId, {
        confidence:
          typeof evt.data.confidence === "number"
            ? (evt.data.confidence as number)
            : null,
        uncertaintyTargets: Array.isArray(evt.data.uncertainty_targets)
          ? (evt.data.uncertainty_targets as string[])
          : [],
        capabilityBoundary: Boolean(evt.data.capability_boundary),
        protocol:
          typeof evt.data.protocol_name === "string"
            ? (evt.data.protocol_name as string)
            : null,
      });
      return next;
    });
  }, []);

  useSidecar(sessionId, handler);

  return { frames };
}
