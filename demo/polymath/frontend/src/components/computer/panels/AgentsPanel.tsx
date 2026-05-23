"use client";

/**
 * AgentsPanel — dockview adapter for the cognitive Agents surface.
 *
 * The Agents tab is the live sub-agent roster (registered + in-flight
 * + recent invocations) — see {@link AgentRoster}. Auto-respawned by
 * the backend's tab middleware on first `agent.*` event so the surface
 * appears the moment the orchestrator spawns its first sub-agent.
 */
import type { IDockviewPanelProps } from "dockview-react";

import { AgentRoster } from "@/components/agents/AgentRoster";

import type { PanelParams } from "./types";

export function AgentsPanel(props: IDockviewPanelProps<PanelParams>) {
  const { sessionId } = props.params;
  return <AgentRoster sessionId={sessionId} />;
}
