"use client";

/**
 * useUIComponents — subscribe to ui.<componentType>.{init,delta,remove}
 * SSE events for one component type and project them into a stable
 * registry keyed by component_id.
 *
 * The dot-path delta op application supports the four mutations Orqest
 * defines in `UIDeltaEvent`:
 *
 *   - replace: overwrite the value at `path`
 *   - merge:   shallow-merge `value` (object) into the dict at `path`
 *   - append:  append `value` to the list at `path`
 *   - remove:  delete the key/element at `path`
 *
 * USAGE:
 *
 *   const { components } = useUIComponents<ChartData>(sessionId, "chart");
 *   {components.map((c) => <ChartRenderer key={c.component_id} spec={c} />)}
 *
 *   // For a per-id selector:
 *   const { components } = useUIComponents<TakeoverDialogData>(sessionId, "takeover_dialog");
 *   const dialog = components[0];
 */

import { useCallback, useState } from "react";

import type { AgentEvent } from "./events";
import { useSidecar } from "./useSidecar";

export type UIDeltaOp = "replace" | "merge" | "append" | "remove";

export interface UIComponentSpec<T = unknown> {
  component_type: string;
  component_id: string;
  data: T;
  metadata: Record<string, unknown>;
  created_at: string;
}

interface UIDeltaPayload {
  component_id: string;
  op: UIDeltaOp;
  /** Dot path into the `data` payload, e.g. "series.0.points". Empty string = root. */
  path: string;
  value: unknown;
}

function applyDelta<T>(
  spec: UIComponentSpec<T>,
  payload: UIDeltaPayload,
): UIComponentSpec<T> {
  const { op, path, value } = payload;
  // Empty path (root replace) is the most common case for "rebuild the spec.data".
  if (path === "" && op === "replace") {
    return { ...spec, data: value as T };
  }

  // Walk the dot-path, immutably copying each parent so React can detect change.
  const segments = path.split(".").filter(Boolean);
  if (segments.length === 0) return spec;

  // Operate on a copy of `data`; clone parents along the path; mutate the leaf.
  const cloneData = structuredClone(spec.data) as Record<string, unknown>;
  let parent: Record<string, unknown> | unknown[] = cloneData;
  for (let i = 0; i < segments.length - 1; i++) {
    const key = segments[i];
    parent = (parent as Record<string, unknown>)[key] as
      | Record<string, unknown>
      | unknown[];
    if (parent === undefined || parent === null) return spec; // Path miss — skip.
  }
  const lastKey = segments[segments.length - 1];

  if (Array.isArray(parent)) {
    const idx = Number(lastKey);
    if (Number.isNaN(idx)) return spec;
    if (op === "replace") parent[idx] = value;
    else if (op === "remove") parent.splice(idx, 1);
    else if (op === "append" && Array.isArray(parent[idx])) {
      (parent[idx] as unknown[]).push(value);
    }
  } else {
    const obj = parent as Record<string, unknown>;
    if (op === "replace") obj[lastKey] = value;
    else if (op === "merge" && typeof obj[lastKey] === "object") {
      obj[lastKey] = { ...(obj[lastKey] as object), ...(value as object) };
    } else if (op === "append") {
      const target = obj[lastKey];
      if (Array.isArray(target)) target.push(value);
    } else if (op === "remove") {
      delete obj[lastKey];
    }
  }

  return { ...spec, data: cloneData as T };
}

export function useUIComponents<T = unknown>(
  sessionId: string,
  componentType: string,
) {
  const [byId, setById] = useState<Map<string, UIComponentSpec<T>>>(
    () => new Map(),
  );

  const initType = `ui.${componentType}.init`;
  const deltaType = `ui.${componentType}.delta`;
  const removeType = `ui.${componentType}.remove`;

  const handler = useCallback(
    (evt: AgentEvent) => {
      if (evt.event_type === initType) {
        const spec = evt.data as unknown as UIComponentSpec<T>;
        if (!spec.component_id) return;
        setById((prev) => {
          const next = new Map(prev);
          next.set(spec.component_id, spec);
          return next;
        });
      } else if (evt.event_type === deltaType) {
        const payload = evt.data as unknown as UIDeltaPayload;
        if (!payload.component_id) return;
        setById((prev) => {
          const spec = prev.get(payload.component_id);
          if (!spec) return prev;
          const next = new Map(prev);
          next.set(payload.component_id, applyDelta(spec, payload));
          return next;
        });
      } else if (evt.event_type === removeType) {
        const id = (evt.data as { component_id?: string }).component_id;
        if (!id) return;
        setById((prev) => {
          if (!prev.has(id)) return prev;
          const next = new Map(prev);
          next.delete(id);
          return next;
        });
      }
    },
    [initType, deltaType, removeType],
  );

  useSidecar(sessionId, handler);

  return {
    components: Array.from(byId.values()),
    byId,
  };
}
