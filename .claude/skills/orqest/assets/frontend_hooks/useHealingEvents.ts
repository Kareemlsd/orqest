"use client";

/**
 * useHealingEvents — project the four healing.* event types into a
 * bounded ring of HealingEntry records suitable for a transient toast
 * stack.
 *
 * Event types projected:
 *   - healing.detection         → kind: "detection" (e.g. "stall · 23s")
 *   - healing.action            → kind: "action"    (policy decided)
 *   - healing.model_fallback    → kind: "fallback"  (FallbackModel advanced)
 *   - healing.model_chain_exhausted → kind: "exhausted" (chain spent)
 *
 * USAGE:
 *
 *   const { entries, dismiss, clear } = useHealingEvents(sessionId);
 *   <HealingToasts entries={entries} onDismiss={dismiss} />
 */

import { useCallback, useState } from "react";

import type { AgentEvent } from "./events";
import { useSidecar } from "./useSidecar";

export type HealingKind =
  | "detection"
  | "action"
  | "fallback"
  | "exhausted";

export interface HealingEntry {
  id: string;
  kind: HealingKind;
  summary: string;
  /** Detector severity (0..1) when applicable; otherwise null. */
  severity: number | null;
  ts: number;
}

function projectEvent(evt: AgentEvent): HealingEntry | null {
  const id = `${evt.timestamp}:${evt.event_type}`;
  const ts = Date.now();
  switch (evt.event_type) {
    case "healing.detection": {
      const detector = String(evt.data.detector ?? "detection");
      const summary = String(evt.data.summary ?? "");
      const severity =
        typeof evt.data.severity === "number"
          ? (evt.data.severity as number)
          : null;
      return {
        id,
        kind: "detection",
        summary: summary || detector,
        severity,
        ts,
      };
    }
    case "healing.action": {
      const action = String(evt.data.action ?? "action");
      return { id, kind: "action", summary: action, severity: null, ts };
    }
    case "healing.model_fallback": {
      const from = String(evt.data.from_model ?? evt.data.from ?? "?");
      const to = String(evt.data.to_model ?? evt.data.to ?? "?");
      return {
        id,
        kind: "fallback",
        summary: `fallback · ${from} → ${to}`,
        severity: null,
        ts,
      };
    }
    case "healing.model_chain_exhausted":
      return {
        id,
        kind: "exhausted",
        summary: "fallback chain exhausted",
        severity: null,
        ts,
      };
    default:
      return null;
  }
}

export function useHealingEvents(sessionId: string, maxItems = 24) {
  const [entries, setEntries] = useState<HealingEntry[]>([]);

  const handler = useCallback(
    (evt: AgentEvent) => {
      if (!evt.event_type.startsWith("healing.")) return;
      const projected = projectEvent(evt);
      if (!projected) return;
      setEntries((prev) => {
        // Newest-first, bounded ring. Dedupe by id (events can replay on
        // reconnect).
        if (prev.some((e) => e.id === projected.id)) return prev;
        const next = [projected, ...prev];
        if (next.length > maxItems) next.length = maxItems;
        return next;
      });
    },
    [maxItems],
  );

  useSidecar(sessionId, handler);

  const dismiss = useCallback((id: string) => {
    setEntries((prev) => prev.filter((e) => e.id !== id));
  }, []);

  const clear = useCallback(() => setEntries([]), []);

  return { entries, dismiss, clear };
}
