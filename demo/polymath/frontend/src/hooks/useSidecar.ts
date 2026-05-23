"use client";

/**
 * useSidecar — context consumer that registers an SSE subscriber on
 * the session-scoped `<SidecarProvider>`.
 *
 * Historical note: this hook used to open its own `EventSource` per
 * call. Polymath calls it from many places (`usePlan`, `useArtifacts`,
 * `useTakeover`, every `useUIComponents` consumer, the session page
 * itself, several Computer-pane tabs), and the per-call connection
 * cost stacked into 4–6 simultaneous SSE connections per session with
 * fan-out re-renders to match. The connection now lives on
 * `<SidecarProvider sessionId>` and this hook is a thin wrapper that
 * registers a handler via `subscribeAll` and tears it down on unmount.
 *
 * Public API is unchanged on purpose — callers (`usePlan`,
 * `useArtifacts`, `useTakeover`, `useUIComponents`, page-level effects)
 * keep their `useSidecar(sessionId, onEvent)` invocation as is.
 *
 * The `sessionId` argument is validated against the provider's session
 * id. A mismatch is a programming error (mounting a hook under the
 * wrong session's provider) and throws so the bug surfaces immediately
 * instead of silently misrouting events.
 */
import { useEffect, useRef } from "react";

import type { AgentEvent } from "@/lib/events";

import { useSidecarContext } from "./SidecarProvider";

type SubscriberCallback = (event: AgentEvent) => void;

export function useSidecar(sessionId: string, onEvent?: SubscriberCallback) {
  const ctx = useSidecarContext();
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  if (sessionId && sessionId !== ctx.sessionId) {
    throw new Error(
      `[useSidecar] sessionId mismatch: hook called with "${sessionId}" but provider scope is "${ctx.sessionId}".`,
    );
  }

  useEffect(() => {
    if (!sessionId) return;
    // Stable internal forwarder so adding/removing a subscription does
    // not require recreating the user's callback identity. The real
    // callback is read from a ref on every dispatch so it always sees
    // the latest closure.
    const forward: SubscriberCallback = (event) => {
      onEventRef.current?.(event);
    };
    return ctx.subscribeAll(forward);
  }, [ctx, sessionId]);
}
