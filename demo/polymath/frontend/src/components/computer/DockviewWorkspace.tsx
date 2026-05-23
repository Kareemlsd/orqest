"use client";

/**
 * DockviewWorkspace — mounts the dockview grid for a single session.
 *
 * Owns the {@link DockviewReact} container, the panel registry, and the
 * Polymath theme class. Does NOT add panels itself — the second agent's
 * `useTabs` hook drives panel mutation through the {@link DockviewApi}
 * we surface via `onApiReady`.
 *
 * Sized to fill its parent (`h-full w-full`); the parent
 * (`ComputerPane`) controls the visible bounds.
 *
 * Renders an editorial empty-state overlay behind the grid when no
 * panels are present — the dockview grid stays mounted (so panels can
 * still be added/dragged into it), but the placeholder explains what
 * tabs are for and what kinds will appear.
 */
import { useCallback, useRef, useState } from "react";
import {
  DockviewReact,
  type DockviewApi,
  type DockviewReadyEvent,
} from "dockview-react";

import { EmptyWorkspaceState } from "./EmptyWorkspaceState";
import { PANEL_COMPONENTS } from "./panels";

export interface DockviewWorkspaceProps {
  sessionId: string;
  onApiReady: (api: DockviewApi) => void;
}

export function DockviewWorkspace({
  sessionId,
  onApiReady,
}: DockviewWorkspaceProps) {
  // Track panel count locally so the empty-state overlay can disappear
  // the moment a panel arrives. We subscribe to dockview's layout
  // change event for this — `panels` is a live array but React won't
  // re-render off it without a state hook bridging the two.
  const [panelCount, setPanelCount] = useState(0);
  const apiRef = useRef<DockviewApi | null>(null);

  const handleReady = useCallback(
    (event: DockviewReadyEvent) => {
      apiRef.current = event.api;
      setPanelCount(event.api.panels.length);
      // Subscribe inline so the listener registers as soon as the
      // dockview api is available — a separate effect would race the
      // initial state hook and could miss the first added panel.
      event.api.onDidLayoutChange(() => {
        setPanelCount(event.api.panels.length);
      });
      onApiReady(event.api);
    },
    [onApiReady],
  );

  // `position: relative` is required — dockview's internal layout uses
  // absolutely-positioned children, and without an explicit relative
  // ancestor the panel content area collapses to zero height. Likewise
  // we render `DockviewReact` inside an `absolute inset-0` wrapper so
  // it always knows its bounding box, regardless of how the parent flex
  // container sizes us.
  return (
    <div
      className="relative h-full w-full dockview-theme-polymath"
      data-session-id={sessionId}
    >
      <div className="absolute inset-0">
        <DockviewReact
          components={PANEL_COMPONENTS}
          onReady={handleReady}
          className="dockview-theme-polymath"
        />
      </div>
      {panelCount === 0 && <EmptyWorkspaceState />}
    </div>
  );
}
