"use client";

/**
 * UIComponentsProvider — session-scoped context that always-on subscribes
 * to every `ui.<type>.{init,delta,remove}` SSE event and exposes the
 * resulting components by id.
 *
 * Why this exists: when a `kind='component'` tab spawns from an
 * `emit_component` call, the backend fires two events back-to-back —
 * `tab.opened` *then* `ui.<type>.init`. The frontend's `tab.opened`
 * handler calls dockview's `addPanel`, which mounts the component-tab
 * panel asynchronously through React's scheduler. By the time
 * `<TabComponentRenderer>` finally mounts and *its* internal
 * `useAllUIComponents` hook subscribes, the `ui.<type>.init` event has
 * already been dispatched and lost — `useSidecar` only sees future
 * events, not historic ones.
 *
 * The fix is to hoist the wildcard subscription to a stable session-
 * level component that mounts the moment the page loads, long before
 * any individual tab spawns. `<TabComponentRenderer>` then becomes a
 * context consumer instead of running its own subscription, so race-
 * arrival ordering no longer matters.
 *
 * Plays nicely with `<SidecarProvider>`: the provider can sit anywhere
 * inside the SidecarProvider subtree.
 */
import { createContext, useContext, type ReactNode } from "react";

import { useAllUIComponents } from "./useAllUIComponents";
import type { UIComponentSpec } from "./useUIComponents";

interface UIComponentsContextValue {
  /** Every emitted UI component by id, excluding types that have a
   *  dedicated surface (`plan`, `chart`, `takeover_dialog`). */
  byId: Map<string, UIComponentSpec>;
  /** All emitted components, sorted newest-first — handy for a
   *  debugging surface or recently-seen list. */
  all: UIComponentSpec[];
}

const Ctx = createContext<UIComponentsContextValue | null>(null);

/**
 * Excluded component types — these have their own dedicated surface
 * (PlanHeader, the legacy chart gallery, TakeoverDialogModal) and
 * shouldn't double-render inside a generic component tab.
 */
const EXCLUDED_TYPES = ["plan", "chart", "takeover_dialog"] as const;

interface UIComponentsProviderProps {
  sessionId: string;
  children: ReactNode;
}

export function UIComponentsProvider({
  sessionId,
  children,
}: UIComponentsProviderProps) {
  const { components, byId } = useAllUIComponents(sessionId, {
    excludeTypes: EXCLUDED_TYPES,
    withById: true,
  });

  return (
    <Ctx.Provider value={{ byId, all: components }}>{children}</Ctx.Provider>
  );
}

/**
 * Read the always-live registry of agent-emitted UI components.
 * Throws when called outside a `<UIComponentsProvider>` so a
 * misconfigured tree fails loudly at mount time.
 */
export function useUIComponentsContext(): UIComponentsContextValue {
  const ctx = useContext(Ctx);
  if (!ctx) {
    throw new Error(
      "[UIComponentsProvider] missing — wrap the session subtree.",
    );
  }
  return ctx;
}
