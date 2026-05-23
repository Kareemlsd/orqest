"use client";

/**
 * useAllUIComponents — wildcard variant of `useUIComponents`. Subscribes
 * to every `ui.<type>.{init,delta,remove}` event for a session and
 * keeps a single map keyed by `component_id` regardless of type.
 *
 * Powers the Canvas tab: a single render slot for every component the
 * agent emits except those that have a dedicated tab (`plan`, `chart`,
 * `takeover_dialog`). The dispatcher (`UIComponentRenderer`) walks the
 * tree from each top-level component, so the wildcard hook only needs
 * to deduplicate by id; nested children come along for free via the
 * recursive renderer.
 *
 * `applyDelta` is shared with `useUIComponents.ts` (re-exported from
 * the renderer registry) so the patch semantics stay byte-identical
 * across the type-scoped and type-wildcard hooks.
 */
import { useMemo, useState } from "react";

import {
  applyDelta,
  type UIComponentSpec,
  type UIDeltaEvent,
} from "@/components/ui-renderers/registry";

import { useSidecar } from "./useSidecar";

interface UseAllUIComponentsOptions {
  excludeTypes?: readonly string[];
}

interface UseAllUIComponentsResult {
  /** Open components, newest first (sorted by `created_at`). */
  components: UIComponentSpec[];
  /** Index by `component_id` for renderers that need to look up by id —
   *  e.g. the `TabComponentRenderer` resolves each component bound to a
   *  tab via this map. */
  byId: Map<string, UIComponentSpec>;
}

export function useAllUIComponents(
  sessionId: string,
  options?: UseAllUIComponentsOptions,
): UIComponentSpec[];
export function useAllUIComponents(
  sessionId: string,
  options: UseAllUIComponentsOptions & { withById: true },
): UseAllUIComponentsResult;
export function useAllUIComponents(
  sessionId: string,
  options?: UseAllUIComponentsOptions & { withById?: boolean },
): UIComponentSpec[] | UseAllUIComponentsResult {
  const exclude = options?.excludeTypes ?? [];
  const [components, setComponents] = useState<Map<string, UIComponentSpec>>(
    () => new Map(),
  );

  useSidecar(sessionId, (evt) => {
    const et = evt.event_type;
    if (!et.startsWith("ui.")) return;
    const parts = et.split(".");
    if (parts.length !== 3) return;
    const componentType = parts[1];
    const op = parts[2];
    if (exclude.includes(componentType)) return;

    if (op === "init") {
      const spec = evt.data as unknown as UIComponentSpec;
      if (!spec || typeof spec.component_id !== "string") return;
      setComponents((prev) => {
        const next = new Map(prev);
        next.set(spec.component_id, spec);
        return next;
      });
    } else if (op === "delta") {
      const delta = evt.data as unknown as UIDeltaEvent;
      if (!delta || typeof delta.component_id !== "string") return;
      setComponents((prev) => {
        const existing = prev.get(delta.component_id);
        if (!existing) return prev;
        const updated = applyDelta(existing, delta);
        if (updated === existing) return prev;
        const next = new Map(prev);
        next.set(delta.component_id, updated);
        return next;
      });
    } else if (op === "remove") {
      const data = evt.data as { component_id?: string };
      const cid = data?.component_id;
      if (typeof cid !== "string") return;
      setComponents((prev) => {
        if (!prev.has(cid)) return prev;
        const next = new Map(prev);
        next.delete(cid);
        return next;
      });
    }
  });

  const sorted = useMemo(() => {
    return Array.from(components.values()).sort((a, b) => {
      const at = Date.parse(a.created_at);
      const bt = Date.parse(b.created_at);
      if (Number.isFinite(at) && Number.isFinite(bt)) return bt - at;
      return b.created_at.localeCompare(a.created_at);
    });
  }, [components]);

  if (options?.withById) {
    return { components: sorted, byId: components };
  }
  return sorted;
}
