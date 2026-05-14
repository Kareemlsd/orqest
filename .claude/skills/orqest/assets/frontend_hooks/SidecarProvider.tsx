"use client";

/**
 * SidecarProvider — owns ONE EventSource per session id and fans out
 * incoming SSE events to many subscribers.
 *
 * Why this exists: multiple hooks (useMetacognition, useHealingEvents,
 * useUIComponents per component_type) would each open their own
 * EventSource. With 4–6 simultaneous SSE connections per session, the
 * backend fans every event out N times and the browser triggers N
 * re-renders for one logical update. This provider collapses that to a
 * single connection — every consumer subscribes through one shared
 * dispatcher.
 *
 * Lifecycle:
 *   - Mount with sessionId → open one EventSource at
 *     `${base}/sessions/${sessionId}/events`
 *   - On any incoming event, dispatch to every handler registered under
 *     that event_type AND every handler registered via subscribeAll
 *   - Reconnect with exponential backoff on error
 *   - On sessionId change, tear down + re-establish; clear subscribers
 *   - On unmount, close the EventSource and clear all handler maps
 *
 * Subscribers can register before the source has connected and remain
 * registered across reconnects. Handlers are stored in
 * Map<eventType, Set<handler>> so add/remove is O(1).
 *
 * USAGE:
 *
 *   <SidecarProvider sessionId={sid} apiBase="https://api.example.com">
 *     <ChatPane />     // calls useMetacognition, useHealingEvents, ...
 *     <Workspace />    // calls useUIComponents(...) per component_type
 *   </SidecarProvider>
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from "react";

import type { AgentEvent } from "./events";

export type SidecarHandler = (event: AgentEvent) => void;

interface SidecarContextValue {
  sessionId: string;
  /** Subscribe to a single SSE event_type. Returns an unsubscribe function. */
  subscribe: (eventType: string, handler: SidecarHandler) => () => void;
  /** Subscribe to every event regardless of type. Returns unsubscribe. */
  subscribeAll: (handler: SidecarHandler) => () => void;
}

const SidecarContext = createContext<SidecarContextValue | null>(null);

export function useSidecarContext(): SidecarContextValue {
  const ctx = useContext(SidecarContext);
  if (!ctx) {
    throw new Error(
      "[Sidecar] No <SidecarProvider> found. Wrap the session subtree.",
    );
  }
  return ctx;
}

interface SidecarProviderProps {
  sessionId: string;
  /** Backend base URL, e.g. `http://localhost:8000` or `https://api.example.com`. */
  apiBase: string;
  /**
   * Optional: if your backend exposes an `/ui/event-types` manifest endpoint,
   * pass `manifestPath` to fetch the list of typed events to listen for.
   * Defaults to relying on the EventSource onmessage fallback (untyped frames).
   */
  manifestPath?: string;
  /** Optional: explicit list of event types to register typed listeners for. */
  eventTypes?: readonly string[];
  children: ReactNode;
}

export function SidecarProvider({
  sessionId,
  apiBase,
  manifestPath,
  eventTypes,
  children,
}: SidecarProviderProps) {
  const handlersByTypeRef = useRef<Map<string, Set<SidecarHandler>>>(new Map());
  const allHandlersRef = useRef<Set<SidecarHandler>>(new Set());

  const dispatch = useCallback((event: AgentEvent) => {
    const typed = handlersByTypeRef.current.get(event.event_type);
    if (typed) {
      for (const handler of Array.from(typed)) {
        try {
          handler(event);
        } catch (err) {
          console.warn("[SidecarProvider] handler threw", err);
        }
      }
    }
    if (allHandlersRef.current.size > 0) {
      for (const handler of Array.from(allHandlersRef.current)) {
        try {
          handler(event);
        } catch (err) {
          console.warn("[SidecarProvider] subscribeAll handler threw", err);
        }
      }
    }
  }, []);

  useEffect(() => {
    if (!sessionId) return;
    let source: EventSource | null = null;
    let backoff = 500;
    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const handleMessage = (raw: MessageEvent) => {
      try {
        const evt: AgentEvent = JSON.parse(raw.data);
        dispatch(evt);
      } catch {
        // Malformed payload — skip.
      }
    };

    const connect = () => {
      if (cancelled) return;
      source = new EventSource(`${apiBase}/sessions/${sessionId}/events`);
      source.onopen = () => {
        backoff = 500;
      };
      // Untyped fallback (events without `event:` header).
      source.onmessage = handleMessage;
      // Typed events — one listener per known event type. EventSource fires
      // either the typed listener or onmessage, never both.
      if (eventTypes) {
        for (const et of eventTypes) {
          source.addEventListener(et, handleMessage as EventListener);
        }
      }
      source.onerror = () => {
        source?.close();
        source = null;
        if (cancelled) return;
        reconnectTimer = setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, 10_000);
      };
    };

    connect();
    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      source?.close();
    };
  }, [sessionId, apiBase, eventTypes, dispatch]);

  // Reset subscribers when sessionId changes — handlers from the previous
  // session would otherwise leak.
  useEffect(() => {
    const typedMap = handlersByTypeRef.current;
    const allSet = allHandlersRef.current;
    return () => {
      typedMap.clear();
      allSet.clear();
    };
  }, [sessionId]);

  const subscribe = useCallback(
    (eventType: string, handler: SidecarHandler) => {
      let bucket = handlersByTypeRef.current.get(eventType);
      if (!bucket) {
        bucket = new Set();
        handlersByTypeRef.current.set(eventType, bucket);
      }
      bucket.add(handler);
      return () => {
        const set = handlersByTypeRef.current.get(eventType);
        if (!set) return;
        set.delete(handler);
        if (set.size === 0) handlersByTypeRef.current.delete(eventType);
      };
    },
    [],
  );

  const subscribeAll = useCallback((handler: SidecarHandler) => {
    allHandlersRef.current.add(handler);
    return () => {
      allHandlersRef.current.delete(handler);
    };
  }, []);

  const value = useMemo<SidecarContextValue>(
    () => ({ sessionId, subscribe, subscribeAll }),
    [sessionId, subscribe, subscribeAll],
  );

  // Suppress unused-var lint while keeping manifestPath in the public API
  // for forward-compat — see references/ai_sdk_integration.md for the
  // manifest fetch pattern (omitted from this generic template to keep it lean).
  void manifestPath;

  return (
    <SidecarContext.Provider value={value}>{children}</SidecarContext.Provider>
  );
}
