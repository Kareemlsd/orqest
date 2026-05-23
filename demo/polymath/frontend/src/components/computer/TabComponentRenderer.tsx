"use client";

/**
 * TabComponentRenderer — renders the components bound to a single
 * `kind='component'` tab.
 *
 * Each tab carries `content_ref.component_ids: string[]` listing the
 * `UIComponentSpec`s the agent emitted for it (via
 * `emit_component(metadata={target_tab_id: ...})`). This component
 * resolves each id against the live UI component map (kept in sync by
 * `useAllUIComponents`) and dispatches each spec through the existing
 * `UIComponentRenderer`.
 *
 * Replaces the wildcard `CanvasTab.tsx` from Phase A: instead of one
 * surface showing every emitted component, each tab is a scoped surface
 * showing only the components bound to it.
 */
import { useMemo } from "react";

import type { Tab } from "@/hooks/useTabs";
import { useUIComponentsContext } from "@/hooks/UIComponentsProvider";

import { UIComponentRenderer } from "@/components/ui-renderers/UIComponentRenderer";

interface TabComponentRendererProps {
  tab: Tab;
  sessionId: string;
}

export function TabComponentRenderer({
  tab,
  sessionId,
}: TabComponentRendererProps) {
  // Read from the always-on registry rather than subscribing on mount —
  // dockview spawns this panel asynchronously after the matching
  // `tab.opened` event, and by the time we'd run our own subscription
  // the corresponding `ui.<type>.init` event would already have been
  // dispatched and lost. The provider mounts at session-page level so
  // we never race the SSE stream.
  const { byId } = useUIComponentsContext();

  const componentIds = useMemo<string[]>(() => {
    const raw = (tab.content_ref?.component_ids ?? []) as unknown;
    if (!Array.isArray(raw)) return [];
    return raw.filter((s): s is string => typeof s === "string");
  }, [tab.content_ref]);

  const specs = useMemo(() => {
    return componentIds
      .map((id) => byId.get(id))
      .filter(<T,>(s: T | undefined): s is T => s !== undefined);
  }, [componentIds, byId]);

  if (specs.length === 0) {
    return (
      <div className="flex flex-col items-start px-6 pt-[20vh]">
        <h2 className="font-serif text-[24px] text-foreground leading-tight">
          {tab.title}
        </h2>
        <p className="mt-2 font-mono text-[11px] text-muted-foreground">
          Waiting for the agent to emit content for this tab.
        </p>
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto p-4 space-y-3">
      {specs.map((spec) => (
        <div
          key={spec.component_id}
          className="rounded-md border border-border-subtle bg-surface-card p-3"
        >
          <UIComponentRenderer spec={spec} sessionId={sessionId} />
        </div>
      ))}
    </div>
  );
}
