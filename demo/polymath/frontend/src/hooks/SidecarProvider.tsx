"use client";

/**
 * SidecarProvider — owns ONE `EventSource` per session id and fans out
 * incoming SSE events to many subscribers.
 *
 * Why this exists: multiple hooks (`usePlan`, `useArtifacts`, `useTakeover`,
 * `useUIComponents` and per-tab `useSidecar` consumers) used to each open
 * their own `EventSource`. With 4–6 simultaneous SSE connections per
 * session, the backend fanned every event out N times and the browser
 * triggered N React re-renders for one logical update. This provider
 * collapses that to a single connection — every consumer subscribes
 * through one shared dispatcher.
 *
 * Lifecycle:
 *   - Mount with `sessionId` → fetch `/ui/event-types` (or fall back to
 *     `_FALLBACK_EVENT_TYPES`) → open one `EventSource`.
 *   - On any incoming event, dispatch to every handler registered under
 *     that `event_type` AND every handler registered via `subscribeAll`.
 *   - Reconnect with exponential backoff on error.
 *   - On `sessionId` change, tear down and re-establish.
 *   - On unmount, close the EventSource and clear all handler maps.
 *
 * Subscription registration is decoupled from the EventSource lifecycle:
 * subscribers can register before the source has connected and remain
 * registered across reconnects. Handlers are stored in a `Map<eventType,
 * Set<handler>>` (with `null` keying the `subscribeAll` set) so adding
 * or removing a single subscriber is O(1).
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { backendBase } from "@/lib/api";
import type { AgentEvent } from "@/lib/events";

export type SidecarHandler = (event: AgentEvent) => void;

/**
 * Graceful-degradation list used when the manifest endpoint is
 * unreachable (older backends without `/ui/event-types`, network
 * failure, dev hot-reload race). Must remain a strict superset of
 * everything any pre-Phase-β backend might emit so connections stay
 * functional even when discovery fails.
 */
const _FALLBACK_EVENT_TYPES: readonly string[] = [
  "heartbeat",
  "plan.init",
  "plan.task.updated",
  "ui.plan.init",
  "ui.plan.delta",
  "ui.takeover_dialog.init",
  "ui.takeover_dialog.delta",
  "ui.takeover_dialog.remove",
  "tool.before",
  "tool.after",
  "tool.error",
  "tool.web_search.started",
  "tool.web_search.completed",
  "tool.web_fetch.started",
  "tool.web_fetch.completed",
  "memory.stored",
  "memory.recalled",
  "shell.stdout",
  "shell.exit",
  "browser.action",
  "artifact.created",
  "agent.spawned",
  "agent.completed",
  "agent.registered",
  "agent.updated",
  "agent.invocation_failed",
  "metacognition.confidence",
  "takeover.activated",
  "takeover.released",
];

interface EventTypesResponse {
  event_types: string[];
}

function isEventTypesResponse(value: unknown): value is EventTypesResponse {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as { event_types?: unknown };
  if (!Array.isArray(candidate.event_types)) return false;
  return candidate.event_types.every((entry) => typeof entry === "string");
}

interface SidecarContextValue {
  sessionId: string;
  /**
   * Subscribe to a single SSE `event_type`. Returns an unsubscribe
   * function. Stable across renders.
   */
  subscribe: (eventType: string, handler: SidecarHandler) => () => void;
  /**
   * Subscribe to every event regardless of type. Mirrors how callers
   * currently use `useSidecar(sessionId, onEvent)`. Returns an
   * unsubscribe function. Stable across renders.
   */
  subscribeAll: (handler: SidecarHandler) => () => void;
}

const SidecarContext = createContext<SidecarContextValue | null>(null);

/**
 * Internal accessor. Hooks like `useSidecar` should use this instead of
 * `useContext` directly so the "no provider" error is consistent.
 */
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
  children: ReactNode;
}

export function SidecarProvider({ sessionId, children }: SidecarProviderProps) {
  // Handler maps: keyed by event_type, plus a separate set for "all".
  // Refs because subscribers come and go without driving renders.
  const handlersByTypeRef = useRef<Map<string, Set<SidecarHandler>>>(new Map());
  const allHandlersRef = useRef<Set<SidecarHandler>>(new Set());

  // Manifest fetch — same semantics as the legacy `useEventTypes`: start
  // with the fallback superset, replace on success, keep fallback on any
  // failure. Resolved list is then written into a ref the EventSource
  // effect reads when (re)connecting.
  const [eventTypes, setEventTypes] = useState<readonly string[]>(
    _FALLBACK_EVENT_TYPES,
  );

  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController();
    const url = `${backendBase()}/sessions/${sessionId}/ui/event-types`;

    fetch(url, { signal: controller.signal })
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`manifest fetch ${res.status}`);
        }
        const payload: unknown = await res.json();
        if (!isEventTypesResponse(payload)) {
          console.warn(
            "[SidecarProvider] /ui/event-types returned malformed payload; falling back to static list",
            payload,
          );
          return;
        }
        setEventTypes(payload.event_types);
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        console.warn(
          "[SidecarProvider] /ui/event-types unreachable; falling back to static list",
          err,
        );
      });

    return () => {
      controller.abort();
    };
  }, [sessionId]);

  // Stable dispatcher. Reads from refs so it doesn't need to re-run when
  // the subscriber map mutates — only the maps themselves change.
  const dispatch = useCallback((event: AgentEvent) => {
    const typed = handlersByTypeRef.current.get(event.event_type);
    if (typed) {
      // Iterate over a snapshot so handlers can unsubscribe themselves
      // mid-dispatch without throwing the iterator.
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

  // EventSource lifecycle. One connection per session, reconnects with
  // exponential backoff, re-registers all known event-type listeners
  // every time it opens (so a manifest swap mid-session keeps working).
  useEffect(() => {
    if (!sessionId) return;
    const base = backendBase();
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
      source = new EventSource(`${base}/sessions/${sessionId}/events`);
      source.onopen = () => {
        backoff = 500;
      };
      // Untyped fallback (heartbeats without `event:` header).
      source.onmessage = handleMessage;
      // Typed events — one listener per resolved event type. The list
      // comes from the manifest fetch above; on failure it remains the
      // fallback superset, so listeners are always registered.
      for (const et of eventTypes) {
        source.addEventListener(et, handleMessage as EventListener);
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
  }, [sessionId, eventTypes, dispatch]);

  // Subscription helpers — stable across renders, return tear-down
  // closures that consumers can pass straight to `useEffect`.
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

  // Reset all subscriber state if the provider's session id changes —
  // handlers registered against the previous session would otherwise
  // leak, and the EventSource has already torn down via the effect
  // above. Capture the refs into local consts so the lint rule against
  // ref-access-in-cleanup is satisfied; in practice the refs hold the
  // same Map for the lifetime of the component (we mutate the contents,
  // never reassign `.current`).
  useEffect(() => {
    const typedMap = handlersByTypeRef.current;
    const allSet = allHandlersRef.current;
    return () => {
      typedMap.clear();
      allSet.clear();
    };
  }, [sessionId]);

  const value = useMemo<SidecarContextValue>(
    () => ({ sessionId, subscribe, subscribeAll }),
    [sessionId, subscribe, subscribeAll],
  );

  return (
    <SidecarContext.Provider value={value}>{children}</SidecarContext.Provider>
  );
}
