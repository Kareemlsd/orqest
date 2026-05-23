"use client";

/**
 * useMemory — feeds the cognitive Memory tab (`kind='memory'`).
 *
 * Hydrates from `GET /sessions/{sid}/memory` on mount, then live-merges
 * the five typed memory events the backend now emits:
 *   - `memory.stored`        — new entry (or upsert) landed
 *   - `memory.entry_updated` — existing entry replaced
 *   - `memory.recall_empty`  — a recall came back with zero hits
 *   - `memory.store_failed`  — store call raised
 *   - `memory.recalled`      — recall produced N hits (used to power
 *                              the "recent recalls" footer)
 *
 * Returns sections grouped by typology + a small ring of recent
 * recalls + recent failures. Pure UI state; no REST mutations from
 * the consumer.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { backendBase } from "@/lib/api";
import type { AgentEvent } from "@/lib/events";

import { useSidecar } from "./useSidecar";

export type MemoryKind = "semantic" | "episodic" | "procedural";

export interface MemoryRow {
  id: string;
  content: string;
  memory_type: MemoryKind | string;
  source_agent: string | null;
  confidence: number | null;
  reliability_score: number | null;
  access_count: number;
  created_at: string | null;
  last_accessed_at: string | null;
  structured_content: Record<string, unknown> | null;
}

export interface MemorySection {
  count: number;
  entries: MemoryRow[];
}

export interface RecallEvent {
  id: string;
  query: string;
  memory_type: string;
  hits: number;
  observed_at: string;
}

export interface MemoryFailure {
  id: string;
  reason: string;
  memory_type: string;
  observed_at: string;
}

export interface UseMemoryResult {
  semantic: MemorySection;
  episodic: MemorySection;
  procedural: MemorySection;
  recentRecalls: RecallEvent[];
  recentFailures: MemoryFailure[];
  refresh: () => Promise<void>;
}

const EMPTY_SECTION: MemorySection = { count: 0, entries: [] };
const RECALL_RING = 8;
const FAILURE_RING = 5;

export function useMemory(sessionId: string): UseMemoryResult {
  const [semantic, setSemantic] = useState<MemorySection>(EMPTY_SECTION);
  const [episodic, setEpisodic] = useState<MemorySection>(EMPTY_SECTION);
  const [procedural, setProcedural] = useState<MemorySection>(EMPTY_SECTION);
  const [recentRecalls, setRecentRecalls] = useState<RecallEvent[]>([]);
  const [recentFailures, setRecentFailures] = useState<MemoryFailure[]>([]);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    try {
      const resp = await fetch(`${backendBase()}/sessions/${sessionId}/memory`);
      if (!resp.ok) return;
      const payload = (await resp.json()) as Record<string, MemorySection>;
      setSemantic(payload.semantic ?? EMPTY_SECTION);
      setEpisodic(payload.episodic ?? EMPTY_SECTION);
      setProcedural(payload.procedural ?? EMPTY_SECTION);
    } catch {
      // SSE will eventually populate; absorbing the error here is fine.
    }
  }, [sessionId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useSidecar(sessionId, (evt: AgentEvent) => {
    const et = evt.event_type;
    if (et === "memory.stored" || et === "memory.entry_updated") {
      // We don't have the full row in the SSE payload (just id + preview);
      // a refresh is the simplest correctness guarantee. Trade-off: one
      // extra GET per write. Acceptable for the typical write rate.
      void refresh();
      return;
    }
    if (et === "memory.recalled") {
      const data = evt.data as Record<string, unknown>;
      const next: RecallEvent = {
        id: makeId("recall"),
        query: String(data.query ?? ""),
        memory_type: String(data.memory_type ?? "any"),
        hits:
          typeof data.hits === "number" ? data.hits : Number(data.hits) || 0,
        observed_at: timestampOf(evt),
      };
      setRecentRecalls((prev) => [next, ...prev].slice(0, RECALL_RING));
      return;
    }
    if (et === "memory.recall_empty") {
      // The "recalled" handler above already pushes a hits=0 row; the
      // typed empty event is emitted *after* recalled, so we'd
      // double-record. Use this only to flag the existing row's
      // explicit empty status if we ever expose it.
      return;
    }
    if (et === "memory.store_failed") {
      const data = evt.data as Record<string, unknown>;
      const next: MemoryFailure = {
        id: makeId("fail"),
        reason: String(data.reason ?? "store failed"),
        memory_type: String(data.memory_type ?? ""),
        observed_at: timestampOf(evt),
      };
      setRecentFailures((prev) => [next, ...prev].slice(0, FAILURE_RING));
      return;
    }
  });

  return useMemo<UseMemoryResult>(
    () => ({
      semantic,
      episodic,
      procedural,
      recentRecalls,
      recentFailures,
      refresh,
    }),
    [semantic, episodic, procedural, recentRecalls, recentFailures, refresh],
  );
}

let _idCounter = 0;
function makeId(prefix: string): string {
  _idCounter = (_idCounter + 1) % 1_000_000;
  return `${prefix}-${Date.now()}-${_idCounter}`;
}

function timestampOf(evt: AgentEvent): string {
  return typeof evt.timestamp === "string"
    ? evt.timestamp
    : new Date().toISOString();
}
