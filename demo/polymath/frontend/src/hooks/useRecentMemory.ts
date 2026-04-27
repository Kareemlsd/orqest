"use client";

/**
 * useRecentMemory — thin adapter over `useMemory(sessionId)` that
 * returns the top-N most recently created entries across all kinds,
 * sorted by `created_at` descending.
 *
 * Used by `<ChatPane>`'s editorial empty state to render the
 * "continuing memory" section — three most-recent threads the agent
 * has been holding for the user.
 */
import { useMemo } from "react";

import type { MemoryKind, MemoryRow } from "./useMemory";
import { useMemory } from "./useMemory";

export interface RecentMemoryEntry {
  id: string;
  kind: MemoryKind | string;
  content: string;
  /** Source row's `created_at` (ISO) — used for relative-time labels. */
  created_at: string | null;
  /** Source row's `source_agent` — useful for attribution when present. */
  source_agent: string | null;
}

interface UseRecentMemoryResult {
  entries: RecentMemoryEntry[];
  /** True while the initial REST hydration in `useMemory` is in flight
   *  AND no SSE has back-filled. We approximate by checking total
   *  entry count — an empty session can never tell us "loading vs
   *  empty" without an explicit flag, and we deliberately avoid
   *  surfacing one to the consumer. */
  isEmpty: boolean;
}

const DEFAULT_LIMIT = 3;

export function useRecentMemory(
  sessionId: string,
  limit: number = DEFAULT_LIMIT,
): UseRecentMemoryResult {
  const memory = useMemory(sessionId);

  return useMemo<UseRecentMemoryResult>(() => {
    const all: MemoryRow[] = [
      ...memory.semantic.entries,
      ...memory.episodic.entries,
      ...memory.procedural.entries,
    ];

    // Sort descending by `created_at`. Rows with a missing timestamp
    // sink to the bottom (not surfaced as "recent").
    all.sort((a, b) => {
      const at = a.created_at ? Date.parse(a.created_at) : 0;
      const bt = b.created_at ? Date.parse(b.created_at) : 0;
      return bt - at;
    });

    const top = all.slice(0, limit).map<RecentMemoryEntry>((row) => ({
      id: row.id,
      kind: row.memory_type,
      content: row.content,
      created_at: row.created_at,
      source_agent: row.source_agent,
    }));

    return {
      entries: top,
      isEmpty: top.length === 0,
    };
  }, [memory.semantic, memory.episodic, memory.procedural, limit]);
}
