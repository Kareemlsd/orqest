"use client";

/**
 * ComputerPane — right pane, now hosting a dockview workspace.
 *
 * Phase D (dockview migration) replaces the hand-rolled
 * `DynamicTabStrip` + `DynamicTabContent` pair with a single
 * `<DockviewWorkspace>`. Dockview owns the active panel, drag-reorder,
 * tab close affordance, and the strip's overflow scroll. `useTabs` is
 * the bridge: REST manifest → dockview panels via the API ref, SSE
 * events → `addPanel` / `setActive` / `setTitle` / `close`, user
 * actions on the workspace → REST mutations.
 *
 * What this component still owns:
 *   - The session header (Polymath's Computer wordmark + Takeover btn)
 *   - The "+ tab" button and recently-closed menu in the header
 *   - The 5 s undo-close toast
 *   - Keyboard shortcuts (Ctrl/Cmd+W close, Ctrl/Cmd+Shift+T undo,
 *     Ctrl/Cmd+Shift+]/[ cycle) that drive dockview directly via the
 *     api ref.
 */
import { useCallback, useEffect, useRef } from "react";

import type { DockviewApi } from "dockview-react";

import { useTabs } from "@/hooks/useTabs";

import { DockviewWorkspace } from "./DockviewWorkspace";
import { RecentlyClosedMenu } from "./RecentlyClosedMenu";
import { TakeoverButton } from "./TakeoverButton";
import { UndoCloseToast } from "./UndoCloseToast";

export function ComputerPane({ sessionId }: { sessionId: string }) {
  // Dockview API ref — populated by `<DockviewWorkspace>`'s `onApiReady`
  // callback once the underlying grid mounts. `useTabs` polls this ref
  // on its hydrate / subscribe paths so it doesn't need to wait for a
  // re-render to get the api.
  const apiRef = useRef<DockviewApi | null>(null);

  const handleApiReady = useCallback((api: DockviewApi) => {
    apiRef.current = api;
  }, []);

  const {
    lastClosed,
    recentlyClosed,
    ackLastClose,
    restoreTab,
    openTab,
  } = useTabs(sessionId, apiRef);

  const handleUndoClose = useCallback(() => {
    if (!lastClosed) return;
    void restoreTab(lastClosed.id);
    ackLastClose();
  }, [lastClosed, restoreTab, ackLastClose]);

  // Keyboard shortcuts. We talk to dockview directly through `apiRef`
  // for close/cycle since dockview is the source of truth for active
  // state and ordering — going through `useTabs` for these would
  // double-bookkeep. Restore stays on `useTabs.restoreTab` because the
  // REST + dockview re-add is wrapped there.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (!(e.metaKey || e.ctrlKey)) return;
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return;
      }
      const api = apiRef.current;
      // Cmd/Ctrl+Shift+T → undo most recent close.
      if (e.shiftKey && (e.key === "T" || e.key === "t")) {
        if (lastClosed) {
          e.preventDefault();
          void restoreTab(lastClosed.id);
          ackLastClose();
          return;
        }
        if (recentlyClosed.length > 0) {
          e.preventDefault();
          void restoreTab(recentlyClosed[0].id);
        }
        return;
      }
      // Cmd/Ctrl+Shift+]/[ → cycle through panels via dockview directly.
      if (e.shiftKey && (e.key === "]" || e.key === "[")) {
        if (!api) return;
        const panels = api.panels;
        if (panels.length === 0) return;
        const active = api.activePanel?.id ?? null;
        const i = active ? panels.findIndex((p) => p.id === active) : -1;
        const dir = e.key === "]" ? 1 : -1;
        const nextIdx = (i === -1 ? 0 : (i + dir + panels.length) % panels.length);
        e.preventDefault();
        panels[nextIdx].api.setActive();
        return;
      }
      // Cmd/Ctrl+W → close active panel.
      if (!e.shiftKey && (e.key === "w" || e.key === "W")) {
        if (!api) return;
        const active = api.activePanel;
        if (!active) return;
        e.preventDefault();
        active.api.close();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [lastClosed, recentlyClosed, restoreTab, ackLastClose]);

  return (
    <div className="flex flex-col h-full bg-background">
      <div className="flex items-center justify-between border-b border-border-subtle px-3 py-2">
        <span className="font-serif text-[15px] text-foreground">
          Polymath&apos;s Computer
        </span>
        <div className="flex items-center gap-2">
          <RecentlyClosedMenu
            closed={recentlyClosed}
            onRestore={(id) => void restoreTab(id)}
          />
          <NewComponentTabButton
            onClick={() =>
              void openTab({
                kind: "component",
                title: "New tab",
                content_ref: {},
              })
            }
          />
          <TakeoverButton sessionId={sessionId} />
        </div>
      </div>
      <div className="flex-1 min-h-0 overflow-hidden">
        <DockviewWorkspace
          sessionId={sessionId}
          onApiReady={handleApiReady}
        />
      </div>
      <UndoCloseToast
        tab={lastClosed}
        onRestore={handleUndoClose}
        onDismiss={ackLastClose}
      />
    </div>
  );
}

function NewComponentTabButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title="Open a new blank tab"
      className="font-mono text-[10px] text-muted-foreground hover:text-foreground transition-colors px-1.5 py-1 rounded-sm hover:bg-surface-elevated"
    >
      + tab
    </button>
  );
}
