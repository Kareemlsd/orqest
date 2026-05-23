"use client";

/**
 * useUIComponents — generic consumer for Orqest's typed `ui.<type>.*` events.
 *
 * Mirrors `orqest.ui.spec.UIComponentSpec[T]` + `UIDeltaEvent` on the
 * frontend. Subscribes to the SSE sidecar and maintains a live registry
 * of components for a single `component_type` (e.g. "chart", "plan",
 * "table", "form", "takeover_dialog").
 *
 * Event protocol (per Phase 8 / Wave 3 contract):
 *   - `ui.<type>.init`   → upsert by `component_id`
 *   - `ui.<type>.delta`  → patch the matching component (replace/merge/append/remove on a dot-path inside `data`)
 *   - `ui.<type>.remove` → delete by `component_id`
 *
 * v1 has **no REST hydration**. The backend's `recent_events` ring buffer
 * + SSE `replay` mechanism (Phase β.5) means new clients catch up on
 * connect. A future v1.5 may add a `GET /sessions/{sid}/ui/snapshot`
 * endpoint if catch-up via replay turns out to be insufficient.
 */
import { useMemo, useState } from "react";

import { useSidecar } from "./useSidecar";

export interface UIComponentSpec<T = unknown> {
  component_type: string;
  component_id: string;
  data: T;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface UIDeltaEvent {
  component_id: string;
  component_type: string;
  op: "replace" | "merge" | "append" | "remove";
  path: string;
  value: unknown;
}

interface UIComponentsResult<T> {
  components: UIComponentSpec<T>[];
  byId: Map<string, UIComponentSpec<T>>;
}

export function useUIComponents<T = unknown>(
  sessionId: string,
  componentType: string,
): UIComponentsResult<T> {
  const [byId, setById] = useState<Map<string, UIComponentSpec<T>>>(
    () => new Map(),
  );

  const initType = `ui.${componentType}.init`;
  const deltaType = `ui.${componentType}.delta`;
  const removeType = `ui.${componentType}.remove`;

  useSidecar(sessionId, (evt) => {
    if (evt.event_type === initType) {
      const spec = evt.data as unknown as UIComponentSpec<T>;
      if (!spec || typeof spec.component_id !== "string") return;
      setById((prev) => {
        const next = new Map(prev);
        next.set(spec.component_id, spec);
        return next;
      });
    } else if (evt.event_type === deltaType) {
      const delta = evt.data as unknown as UIDeltaEvent;
      if (!delta || typeof delta.component_id !== "string") return;
      setById((prev) => {
        const current = prev.get(delta.component_id);
        if (!current) return prev;
        const next = new Map(prev);
        next.set(delta.component_id, applyDelta(current, delta));
        return next;
      });
    } else if (evt.event_type === removeType) {
      const payload = evt.data as { component_id?: string };
      const cid = payload?.component_id;
      if (typeof cid !== "string") return;
      setById((prev) => {
        if (!prev.has(cid)) return prev;
        const next = new Map(prev);
        next.delete(cid);
        return next;
      });
    }
  });

  // Sorted snapshot — newest first by `created_at`. Memoised so consumers
  // can rely on referential stability across renders that don't change
  // the underlying map.
  const components = useMemo(() => {
    return Array.from(byId.values()).sort((a, b) => {
      // Descending: newer dates come first. Fall back to string compare
      // for non-ISO timestamps.
      const ta = Date.parse(a.created_at);
      const tb = Date.parse(b.created_at);
      if (Number.isFinite(ta) && Number.isFinite(tb)) return tb - ta;
      return b.created_at.localeCompare(a.created_at);
    });
  }, [byId]);

  return { components, byId };
}

/**
 * applyDelta — pure, immutable application of a `UIDeltaEvent` to a
 * `UIComponentSpec`. Operates on the dot-path inside `data`.
 *
 *   - replace: set the value at `path` to `delta.value`
 *   - merge:   shallow-merge `delta.value` (object) into the value at `path`
 *   - append:  push `delta.value` onto the array at `path`
 *   - remove:  delete the key at `path` (object) or splice (array index)
 *
 * An empty `path` ("" or ".") targets `data` itself.
 *
 * Defensive against malformed deltas — returns the original `spec`
 * unchanged when `path` cannot be resolved or the op is incompatible
 * with the target type.
 */
export function applyDelta<T>(
  spec: UIComponentSpec<T>,
  delta: UIDeltaEvent,
): UIComponentSpec<T> {
  const segments = splitPath(delta.path);
  const newData = applyAtPath(spec.data, segments, delta.op, delta.value);
  if (newData === spec.data) return spec;
  return { ...spec, data: newData as T };
}

function splitPath(path: string): string[] {
  if (!path || path === ".") return [];
  // Strip leading "." for ergonomics, then split.
  const trimmed = path.startsWith(".") ? path.slice(1) : path;
  return trimmed.split(".").filter((s) => s.length > 0);
}

function applyAtPath(
  current: unknown,
  segments: string[],
  op: UIDeltaEvent["op"],
  value: unknown,
): unknown {
  if (segments.length === 0) {
    return applyOp(current, op, value);
  }
  const [head, ...tail] = segments;
  if (Array.isArray(current)) {
    const idx = Number(head);
    if (!Number.isInteger(idx) || idx < 0 || idx >= current.length) {
      return current;
    }
    const child = applyAtPath(current[idx], tail, op, value);
    if (child === current[idx]) return current;
    const next = current.slice();
    next[idx] = child;
    return next;
  }
  if (current && typeof current === "object") {
    const obj = current as Record<string, unknown>;
    if (tail.length === 0 && op === "remove") {
      if (!(head in obj)) return current;
      const next: Record<string, unknown> = { ...obj };
      delete next[head];
      return next;
    }
    const childCurrent = obj[head];
    const child = applyAtPath(childCurrent, tail, op, value);
    if (child === childCurrent) return current;
    return { ...obj, [head]: child };
  }
  // Path goes deeper than the data structure supports — bail.
  return current;
}

function applyOp(current: unknown, op: UIDeltaEvent["op"], value: unknown): unknown {
  switch (op) {
    case "replace":
      return value;
    case "merge":
      if (
        current &&
        typeof current === "object" &&
        !Array.isArray(current) &&
        value &&
        typeof value === "object" &&
        !Array.isArray(value)
      ) {
        return {
          ...(current as Record<string, unknown>),
          ...(value as Record<string, unknown>),
        };
      }
      return current;
    case "append":
      if (Array.isArray(current)) {
        return [...current, value];
      }
      return current;
    case "remove":
      // Removing the root means clearing it. Use `null` as a benign
      // sentinel; consumers should normally target a sub-path with
      // `remove`.
      return null;
    default:
      return current;
  }
}
