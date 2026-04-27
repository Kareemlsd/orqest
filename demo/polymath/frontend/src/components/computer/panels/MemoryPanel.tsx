"use client";

/**
 * MemoryPanel — dockview adapter for the cognitive Memory surface.
 *
 * The Memory tab is the three-section browser (semantic / episodic /
 * procedural) — see {@link MemoryBrowser}. Auto-respawned by the
 * backend's tab middleware on first `memory.*` event so the surface
 * appears the moment the agent's cognitive memory engages.
 */
import type { IDockviewPanelProps } from "dockview-react";

import { MemoryBrowser } from "@/components/memory/MemoryBrowser";

import type { PanelParams } from "./types";

export function MemoryPanel(props: IDockviewPanelProps<PanelParams>) {
  const { sessionId } = props.params;
  return <MemoryBrowser sessionId={sessionId} />;
}
