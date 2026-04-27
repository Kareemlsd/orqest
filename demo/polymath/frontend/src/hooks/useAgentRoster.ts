"use client";

/**
 * useAgentRoster — feeds the cognitive Agents tab.
 *
 * Hydrates from `GET /sessions/{sid}/agents/roster` on mount, then
 * live-merges five typed `agent.*` events:
 *   - `agent.spawned`             — new dynamic agent invoked
 *   - `agent.completed`           — invocation finished (carries
 *                                   confidence + capability_boundary)
 *   - `agent.registered`          — sub-agent registered to the roster
 *   - `agent.updated`             — existing roster entry replaced
 *   - `agent.invocation_failed`   — invoke called for a missing agent
 *
 * Returns the roster (registered agents) plus a small ring of
 * recent invocations so the surface can show "in-flight" / "just
 * completed" rows distinct from the long-lived registry.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { backendBase } from "@/lib/api";
import type { AgentEvent } from "@/lib/events";

import { useSidecar } from "./useSidecar";

export interface AgentRow {
  name: string;
  role: string | null;
  model: string | null;
  tools: string[];
  tool_count: number;
  reliability_score: number | null;
  access_count: number;
  created_at: string | null;
  last_invoked_at: string | null;
}

export interface AgentInvocation {
  /** Stable id derived from the event run_id + ms timestamp. */
  id: string;
  name: string;
  role: string | null;
  status: "in_flight" | "completed" | "failed";
  confidence: number | null;
  capability_boundary: boolean;
  finding_count: number | null;
  error: string | null;
  observed_at: string;
  /** True until a matching `agent.completed` lands. */
  completed_at: string | null;
}

interface RosterResponse {
  agents: AgentRow[];
  count: number;
}

export interface UseAgentRosterResult {
  roster: AgentRow[];
  /** Most-recent first; bounded to RECENT_RING. */
  recentInvocations: AgentInvocation[];
  inFlight: AgentInvocation[];
  refresh: () => Promise<void>;
}

const RECENT_RING = 12;

export function useAgentRoster(sessionId: string): UseAgentRosterResult {
  const [roster, setRoster] = useState<AgentRow[]>([]);
  const [invocations, setInvocations] = useState<AgentInvocation[]>([]);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    try {
      const resp = await fetch(
        `${backendBase()}/sessions/${sessionId}/agents/roster`,
      );
      if (!resp.ok) return;
      const payload = (await resp.json()) as RosterResponse;
      setRoster(payload.agents ?? []);
    } catch {
      // SSE will populate as events arrive.
    }
  }, [sessionId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useSidecar(sessionId, (evt: AgentEvent) => {
    const et = evt.event_type;
    if (
      et !== "agent.spawned" &&
      et !== "agent.completed" &&
      et !== "agent.registered" &&
      et !== "agent.updated" &&
      et !== "agent.invocation_failed"
    ) {
      return;
    }
    const data = evt.data as Record<string, unknown>;
    const observed_at = timestampOf(evt);

    // Roster mutations — registered / updated entries can change tools
    // or role; cheapest correct refresh is a re-GET.
    if (et === "agent.registered" || et === "agent.updated") {
      void refresh();
      return;
    }

    if (et === "agent.spawned") {
      const inv: AgentInvocation = {
        id: invocationId(data),
        name: String(data.name ?? "agent"),
        role: typeof data.role === "string" ? data.role : null,
        status: "in_flight",
        confidence: null,
        capability_boundary: false,
        finding_count: null,
        error: null,
        observed_at,
        completed_at: null,
      };
      setInvocations((prev) => [inv, ...prev].slice(0, RECENT_RING));
      return;
    }

    if (et === "agent.completed") {
      const id = invocationId(data);
      const ok = data.ok !== false;
      const completedStatus: AgentInvocation["status"] = ok
        ? "completed"
        : "failed";
      const next: Partial<AgentInvocation> = {
        status: completedStatus,
        confidence:
          typeof data.confidence === "number" ? data.confidence : null,
        capability_boundary: Boolean(data.capability_boundary),
        finding_count:
          typeof data.finding_count === "number"
            ? data.finding_count
            : null,
        error: ok ? null : String(data.error ?? "failed"),
        completed_at: observed_at,
      };
      setInvocations((prev) => {
        const idx = prev.findIndex((i) => i.id === id);
        if (idx === -1) {
          // No matching spawn — synthesise a row so the surface still
          // shows the completion (e.g. happens if SSE replay misses
          // the spawn but lands the completion).
          return [
            {
              id,
              name: String(data.name ?? "agent"),
              role: null,
              status: completedStatus,
              confidence:
                typeof data.confidence === "number" ? data.confidence : null,
              capability_boundary: Boolean(data.capability_boundary),
              finding_count:
                typeof data.finding_count === "number"
                  ? data.finding_count
                  : null,
              error: ok ? null : String(data.error ?? "failed"),
              observed_at,
              completed_at: observed_at,
            },
            ...prev,
          ].slice(0, RECENT_RING);
        }
        const merged = { ...prev[idx], ...next };
        return [merged, ...prev.slice(0, idx), ...prev.slice(idx + 1)].slice(
          0,
          RECENT_RING,
        );
      });
      // Completion may have updated the roster's last_invoked timestamp.
      void refresh();
      return;
    }

    if (et === "agent.invocation_failed") {
      const inv: AgentInvocation = {
        id: invocationId(data),
        name: String(data.name ?? "agent"),
        role: null,
        status: "failed",
        confidence: null,
        capability_boundary: false,
        finding_count: null,
        error: String(data.reason ?? "not_registered"),
        observed_at,
        completed_at: observed_at,
      };
      setInvocations((prev) => [inv, ...prev].slice(0, RECENT_RING));
      return;
    }
  });

  const inFlight = useMemo(
    () => invocations.filter((i) => i.status === "in_flight"),
    [invocations],
  );

  return useMemo<UseAgentRosterResult>(
    () => ({
      roster,
      recentInvocations: invocations,
      inFlight,
      refresh,
    }),
    [roster, invocations, inFlight, refresh],
  );
}

let _idCounter = 0;
function invocationId(data: Record<string, unknown>): string {
  const runId = typeof data.run_id === "string" ? data.run_id : null;
  if (runId) return `inv-${runId}`;
  _idCounter = (_idCounter + 1) % 1_000_000;
  return `inv-${Date.now()}-${_idCounter}`;
}

function timestampOf(evt: AgentEvent): string {
  return typeof evt.timestamp === "string"
    ? evt.timestamp
    : new Date().toISOString();
}
