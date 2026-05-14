"use client";

/**
 * useSidecar — context consumer that registers an SSE subscriber on the
 * session-scoped <SidecarProvider>. Stable across renders; tears down on
 * unmount.
 *
 * Pass `sessionId` as a sanity check — a mismatch (mounting under the
 * wrong provider) throws so the bug surfaces immediately.
 */
import { useEffect, useRef } from "react";

import type { AgentEvent } from "./events";
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
    // Stable forwarder — the user's callback is read from a ref so the
    // subscription doesn't re-register every time the consumer re-renders.
    const forward: SubscriberCallback = (event) => {
      onEventRef.current?.(event);
    };
    return ctx.subscribeAll(forward);
  }, [ctx, sessionId]);
}
