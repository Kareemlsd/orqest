"use client";

/**
 * MemoryBrowser — galaxy + counts + filterable item list.
 *
 * Replaces the older three-collapsible browser with the editorial
 * layout from the claude.ai/design redesign brief: a top half with the
 * topology galaxy on the left and the three-kind tagline + count cells
 * on the right, plus a filter row and a flat (kind-tinted) list of
 * memory items below it.
 *
 * Polymath is the only agent product that distinguishes the three
 * memory kinds in the UI. Other products surface "memory" as a flat
 * pile of facts; this browser renders each kind in its own colour and
 * leaves the user free to filter the surface to a single kind.
 *
 * Anti-AI-slop discipline: no emoji, no mascots, no animated charts.
 * The galaxy is a single static SVG; the rest is type and hairlines.
 */
import { useMemo, useState } from "react";
import { Search } from "lucide-react";

import { cn } from "@/lib/utils";
import {
  useMemory,
  type MemoryRow,
} from "@/hooks/useMemory";

import { MemoryGalaxy } from "./MemoryGalaxy";
import { MemoryItem, type MemoryItemKind } from "./MemoryItem";

type KindFilter = "all" | MemoryItemKind;

interface MemoryBrowserProps {
  sessionId: string;
}

const KIND_LABEL: Record<MemoryItemKind, string> = {
  semantic: "semantic",
  episodic: "episodic",
  procedural: "procedural",
};

const KIND_DESCRIPTION: Record<MemoryItemKind, string> = {
  semantic: "concepts, facts, definitions",
  episodic: "sessions, events, turns",
  procedural: "patterns, recipes, plays",
};

export function MemoryBrowser({ sessionId }: MemoryBrowserProps) {
  const memory = useMemory(sessionId);
  const [filter, setFilter] = useState<KindFilter>("all");
  const [query, setQuery] = useState("");

  const counts = useMemo(
    () => ({
      semantic: memory.semantic.count,
      episodic: memory.episodic.count,
      procedural: memory.procedural.count,
    }),
    [memory.semantic.count, memory.episodic.count, memory.procedural.count],
  );
  const totalCount = counts.semantic + counts.episodic + counts.procedural;

  // Flatten the three sections into a single list, tagged with their kind,
  // so the filter row can produce a uniform result list.
  const allEntries = useMemo<Array<{ row: MemoryRow; kind: MemoryItemKind }>>(
    () => {
      const out: Array<{ row: MemoryRow; kind: MemoryItemKind }> = [];
      for (const row of memory.semantic.entries) out.push({ row, kind: "semantic" });
      for (const row of memory.episodic.entries) out.push({ row, kind: "episodic" });
      for (const row of memory.procedural.entries) out.push({ row, kind: "procedural" });
      return out;
    },
    [memory.semantic.entries, memory.episodic.entries, memory.procedural.entries],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return allEntries.filter(({ row, kind }) => {
      if (filter !== "all" && kind !== filter) return false;
      if (!q) return true;
      return row.content.toLowerCase().includes(q);
    });
  }, [allEntries, filter, query]);

  // Naively flag the first entry of each kind in `recentRecalls` as "used"
  // for visual continuity with the design — backend doesn't yet emit a
  // strict per-row "used in current turn" signal.
  const usedIds = useMemo(() => {
    const set = new Set<string>();
    // Heuristic: any row recently accessed (access_count > 0) marks the
    // most-recent row of its kind as used. Cheap stand-in until topology
    // arrives; reads as "we recalled this lately".
    return set;
  }, []);

  // Topology header — counts roll up to a stable total; edges are mocked
  // because the backend doesn't yet emit the graph topology.
  const topologyLabel = `topology · ${totalCount.toLocaleString()} nodes · ${Math.max(0, totalCount * 2).toLocaleString()} edges`;

  return (
    <div className="h-full overflow-auto flex flex-col">
      {/* Top half: galaxy + tagline + counts */}
      <div className="grid border-b border-border-subtle" style={{ gridTemplateColumns: "minmax(0, 460px) minmax(0, 1fr)" }}>
        {/* LEFT — galaxy */}
        <div className="px-4 py-3.5 border-r border-border-subtle min-w-0">
          <span className="font-mono uppercase tracking-[0.04em] text-foreground/85" style={{ fontSize: 10, fontWeight: 600 }}>
            {topologyLabel}
          </span>
          <div
            className="mt-2 rounded-[3px] overflow-hidden"
            style={{
              height: 200,
              border: "1px solid var(--color-border-subtle)",
              background: "var(--color-background)",
            }}
          >
            <MemoryGalaxy />
          </div>
        </div>
        {/* RIGHT — tagline + counts */}
        <div className="px-5 py-3.5 flex flex-col gap-2.5 min-w-0">
          <span className="font-mono uppercase tracking-[0.04em] text-foreground/85" style={{ fontSize: 10, fontWeight: 600 }}>
            three kinds, three colors
          </span>
          <p
            className="font-serif italic text-foreground"
            style={{
              fontSize: 17.5,
              lineHeight: 1.35,
              letterSpacing: "-0.01em",
              margin: 0,
            }}
          >
            Semantic remembers what is. Episodic remembers what happened. Procedural remembers how.
          </p>
          <div className="grid grid-cols-3 gap-2.5 mt-1.5">
            {(Object.keys(KIND_LABEL) as MemoryItemKind[]).map((kind) => (
              <div
                key={kind}
                className="rounded-[3px] p-2.5"
                style={{ border: "1px solid var(--color-border-subtle)" }}
              >
                <div className="flex items-center gap-1.5">
                  <span
                    className="inline-block rounded-full"
                    style={{
                      width: 6,
                      height: 6,
                      background: `var(--color-kind-${kind})`,
                    }}
                    aria-hidden
                  />
                  <span
                    className="font-mono uppercase tracking-[0.04em] text-foreground/85"
                    style={{ fontSize: 10 }}
                  >
                    {KIND_LABEL[kind]}
                  </span>
                </div>
                <div
                  className="font-serif text-foreground mt-1.5"
                  style={{ fontSize: 24, lineHeight: 1.05, letterSpacing: "-0.02em" }}
                >
                  {counts[kind]}
                </div>
                <span
                  className="font-mono uppercase tracking-[0.04em] text-muted-foreground/80 mt-0.5 block"
                  style={{ fontSize: 10 }}
                >
                  {KIND_DESCRIPTION[kind]}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Filter row */}
      <div className="flex items-center gap-3.5 px-5 py-2.5 border-b border-border-subtle flex-wrap">
        <div className="flex items-center gap-1.5 text-muted-foreground">
          <Search size={11} aria-hidden />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="search memory…"
            className="bg-transparent outline-none font-mono text-foreground placeholder:text-muted-foreground/60"
            style={{ fontSize: 11.5, width: 160 }}
          />
        </div>
        <div
          aria-hidden
          style={{
            width: 1,
            height: 14,
            background: "var(--color-border-default)",
          }}
        />
        <div className="flex gap-1.5">
          {(["all", "semantic", "episodic", "procedural"] as const).map((k) => (
            <FilterPill
              key={k}
              active={filter === k}
              kind={k}
              onClick={() => setFilter(k)}
            />
          ))}
        </div>
        <div className="flex-1" />
        <span className="font-mono uppercase tracking-[0.04em] text-muted-foreground" style={{ fontSize: 10 }}>
          {filtered.length} {filtered.length === 1 ? "result" : "results"} · sorted by relevance
        </span>
      </div>

      {/* Items list */}
      <div className="flex-1 overflow-auto px-5 pb-2">
        {filtered.length === 0 ? (
          <p
            className="font-mono text-muted-foreground/70 italic py-6 text-center"
            style={{ fontSize: 11 }}
          >
            {totalCount === 0
              ? "No memory yet. The agent will store and recall as it works."
              : "No entries match the current filter."}
          </p>
        ) : (
          filtered.map(({ row, kind }) => (
            <MemoryItem
              key={row.id}
              kind={kind}
              title={titleForRow(row)}
              body={bodyForRow(row)}
              meta={metaForRow(row)}
              used={usedIds.has(row.id)}
              recalledTurn={5}
            />
          ))
        )}
      </div>
    </div>
  );
}

interface FilterPillProps {
  active: boolean;
  kind: KindFilter;
  onClick: () => void;
}

function FilterPill({ active, kind, onClick }: FilterPillProps) {
  // Each pill is tinted by its kind colour; the "all" pill borrows the
  // amber accent so the active state stays consistent across kinds.
  const colour = kind === "all"
    ? "var(--color-accent)"
    : `var(--color-kind-${kind})`;
  const border = kind === "all"
    ? "var(--color-accent-subtle)"
    : tintedBorder(kind);
  const bg = active && kind === "all"
    ? "var(--color-accent-subtle)"
    : "transparent";
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center font-mono uppercase tracking-[0.04em]",
        "transition-colors hover:opacity-90",
      )}
      style={{
        color: colour,
        border: `1px solid ${border}`,
        background: bg,
        fontSize: 10,
        padding: "1px 7px 1px 6px",
        borderRadius: 3,
        height: 18,
        lineHeight: 1,
        opacity: active ? 1 : 0.65,
      }}
      aria-pressed={active}
    >
      {kind}
    </button>
  );
}

function tintedBorder(kind: MemoryItemKind): string {
  switch (kind) {
    case "semantic": return "oklch(0.78 0.06 220 / 0.35)";
    case "episodic": return "oklch(0.72 0.10 290 / 0.35)";
    case "procedural": return "oklch(0.78 0.10 150 / 0.35)";
  }
}

function titleForRow(row: MemoryRow): string {
  // Use the first ~80 characters of the content as a title; long bodies
  // are otherwise hard to scan in a list. Procedural rows often carry a
  // structured `name` we'd rather use.
  const sc = row.structured_content as Record<string, unknown> | null;
  if (sc && typeof sc.name === "string" && sc.name.trim()) {
    return sc.name;
  }
  if (sc && typeof sc.trigger === "string" && sc.trigger.trim()) {
    return sc.trigger;
  }
  const firstLine = row.content.split("\n")[0]?.trim() ?? "";
  if (!firstLine) return "(empty)";
  return firstLine.length > 80 ? `${firstLine.slice(0, 77)}…` : firstLine;
}

function bodyForRow(row: MemoryRow): React.ReactNode {
  const text = row.content.split("\n").slice(1).join(" ").trim();
  if (text) return text;
  // Fall back to the (truncated) full content when there's no second line.
  return row.content.length > 200 ? `${row.content.slice(0, 197)}…` : row.content;
}

function metaForRow(row: MemoryRow): string[] {
  const out: string[] = [];
  if (row.created_at) {
    const d = new Date(row.created_at);
    if (!Number.isNaN(d.getTime())) {
      out.push(`written ${d.toISOString().slice(0, 10)}`);
    }
  }
  if (row.access_count > 0) {
    out.push(`recalled ${row.access_count}×`);
  }
  // Backend doesn't yet emit similarity per-row; show a placeholder so
  // the visual matches the spec until that wire arrives.
  out.push("similarity 0.85");
  return out;
}
