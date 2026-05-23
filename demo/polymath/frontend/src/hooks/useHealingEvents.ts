"use client";

/**
 * useHealingEvents — collects the agent's self-repair signals so the
 * chrome can surface them.
 *
 * The healing subsystem (`orqest.healing`) emits five typed events:
 *   - `healing.detection`        — a watchdog flagged something
 *   - `healing.action`           — the policy chose a recovery action
 *   - `healing.retry_initiated`  — the same tool is being retried
 *   - `healing.model_fallback`   — model chain advanced (e.g. openai → anthropic)
 *   - `healing.model_chain_exhausted` — the whole chain failed; the agent gives up
 *
 * Every other agent product on the market hides these moments. Polymath
 * surfaces them as transient toasts so the user can see "the agent
 * dealt with infrastructure problems and recovered" — confidence-
 * building, even when (especially when) things go briefly wrong.
 *
 * The hook keeps a small ring of the most recent events and lets the
 * toast layer dismiss them individually. Auto-prune past `maxItems`
 * keeps memory bounded if a long session triggers many detections.
 */
import { useCallback, useMemo, useState } from "react";

import type { AgentEvent } from "@/lib/events";

import { useSidecar } from "./useSidecar";

export type HealingKind =
  | "detection"
  | "action"
  | "retry_initiated"
  | "model_fallback"
  | "model_chain_exhausted";

export interface HealingEntry {
  /** Stable id for dismissal — derived from event timestamp + counter. */
  id: string;
  kind: HealingKind;
  /** Mono-style header line — `stall · 23s` / `loop · ×4` / `fallback · openai → anthropic`. */
  header: string;
  /** Muted second line giving the recovery action / context. */
  detail: string;
  /** 0..1 severity (only filled for detection/action). */
  severity: number;
  /** Origin event timestamp for deduping + chronological order. */
  observed_at: string;
}

interface UseHealingEventsResult {
  /** Most-recent first, undismissed entries only. */
  recent: HealingEntry[];
  dismiss: (id: string) => void;
  clearAll: () => void;
}

const MAX_ITEMS_DEFAULT = 24;

export function useHealingEvents(
  sessionId: string,
  maxItems: number = MAX_ITEMS_DEFAULT,
): UseHealingEventsResult {
  const [entries, setEntries] = useState<HealingEntry[]>([]);
  const [dismissed, setDismissed] = useState<Set<string>>(() => new Set());

  useSidecar(sessionId, (evt: AgentEvent) => {
    const projected = projectEvent(evt);
    if (!projected) return;
    setEntries((prev) => {
      const next = [projected, ...prev];
      if (next.length > maxItems) next.length = maxItems;
      return next;
    });
  });

  const dismiss = useCallback((id: string) => {
    setDismissed((prev) => {
      if (prev.has(id)) return prev;
      const next = new Set(prev);
      next.add(id);
      return next;
    });
  }, []);

  const clearAll = useCallback(() => {
    setEntries([]);
    setDismissed(new Set());
  }, []);

  const recent = useMemo(
    () => entries.filter((e) => !dismissed.has(e.id)),
    [entries, dismissed],
  );

  return { recent, dismiss, clearAll };
}

let _idCounter = 0;

function nextId(prefix: string): string {
  _idCounter = (_idCounter + 1) % 1_000_000;
  return `${prefix}-${Date.now()}-${_idCounter}`;
}

function projectEvent(evt: AgentEvent): HealingEntry | null {
  const et = evt.event_type;
  if (!et?.startsWith("healing.")) return null;
  const kind = et.slice("healing.".length) as HealingKind;
  const data = (evt.data ?? {}) as Record<string, unknown>;
  const observed_at =
    typeof evt.timestamp === "string" ? evt.timestamp : new Date().toISOString();

  if (kind === "detection") {
    const det = (data.detection ?? data) as Record<string, unknown>;
    const detector = String(det.detector ?? "watchdog");
    const summary = String(det.summary ?? "detection fired");
    const severity = numeric(det.severity);
    return {
      id: nextId(kind),
      kind,
      header: detector,
      detail: summary,
      severity,
      observed_at,
    };
  }

  if (kind === "action") {
    const det = (data.detection ?? {}) as Record<string, unknown>;
    const action = (data.action ?? {}) as Record<string, unknown>;
    const detector = String(det.detector ?? "watchdog");
    const verdict =
      typeof action.kind === "string"
        ? action.kind
        : typeof action === "object" && action !== null
          ? Object.keys(action).find((k) => k !== "kind") ?? "abort"
          : "abort";
    return {
      id: nextId(kind),
      kind,
      header: `${detector} → ${verdict}`,
      detail: String(action.reason ?? det.summary ?? ""),
      severity: numeric(det.severity),
      observed_at,
    };
  }

  if (kind === "retry_initiated") {
    return {
      id: nextId(kind),
      kind,
      header: `retry · ${String(data.tool_name ?? "")}`,
      detail: String(data.summary ?? data.detector ?? ""),
      severity: numeric(data.severity),
      observed_at,
    };
  }

  if (kind === "model_fallback") {
    const from = String(data.from ?? "?");
    const to = String(data.to ?? "?");
    return {
      id: nextId(kind),
      kind,
      header: `fallback · ${from} → ${to}`,
      detail: String(data.error ?? data.error_type ?? ""),
      severity: 0.6,
      observed_at,
    };
  }

  if (kind === "model_chain_exhausted") {
    const tried = Array.isArray(data.models_tried)
      ? (data.models_tried as unknown[]).map((s) => String(s)).join(", ")
      : "all models";
    return {
      id: nextId(kind),
      kind,
      header: "fallback chain exhausted",
      detail: `tried ${tried} · ${String(data.last_error ?? "")}`.trim(),
      severity: 1,
      observed_at,
    };
  }

  return null;
}

function numeric(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}
