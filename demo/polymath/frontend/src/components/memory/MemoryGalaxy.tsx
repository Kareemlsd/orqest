"use client";

/**
 * MemoryGalaxy — ambient SVG constellation that hints at the shape of
 * the agent's memory store.
 *
 * The visual is a hand-arranged set of nodes coloured by memory kind
 * (semantic / episodic / procedural), threaded with a few faint links,
 * with one cluster ringed in amber to mark the most-recently-recalled
 * grouping. The point is editorial atmosphere — a small reminder that
 * memory is a graph, not a list — not literal data visualisation.
 *
 * Backend topology data isn't yet emitted; the layout is therefore
 * mocked. When the real topology lands, swap `nodes` / `links` for a
 * derived layout but keep the visual grammar (kind colours, amber
 * highlight ring + mono label) intact.
 */
import { useMemo } from "react";

interface MemoryGalaxyProps {
  /** Optional turn label for the highlight ring (defaults to a placeholder). */
  recalledTurn?: number;
}

type GalaxyNode = {
  x: number;
  y: number;
  r: number;
  kind: "semantic" | "episodic" | "procedural";
};

const NODES: ReadonlyArray<GalaxyNode> = [
  { x: 80, y: 60, r: 3, kind: "semantic" },
  { x: 130, y: 110, r: 2, kind: "semantic" },
  { x: 200, y: 80, r: 4, kind: "semantic" },
  { x: 260, y: 140, r: 2, kind: "episodic" },
  { x: 320, y: 90, r: 3, kind: "procedural" },
  { x: 380, y: 160, r: 2, kind: "semantic" },
  { x: 100, y: 180, r: 2, kind: "episodic" },
  { x: 170, y: 200, r: 3, kind: "episodic" },
  { x: 240, y: 220, r: 2, kind: "procedural" },
  { x: 310, y: 200, r: 2, kind: "procedural" },
  { x: 60, y: 130, r: 2, kind: "semantic" },
  { x: 360, y: 50, r: 2, kind: "semantic" },
  { x: 410, y: 110, r: 3, kind: "episodic" },
  { x: 50, y: 230, r: 2, kind: "procedural" },
] as const;

const LINKS: ReadonlyArray<readonly [number, number]> = [
  [0, 2], [2, 4], [4, 11], [2, 5], [5, 12],
  [7, 8], [8, 9], [6, 7], [1, 2], [10, 1],
] as const;

function colourFor(kind: GalaxyNode["kind"]): string {
  switch (kind) {
    case "semantic": return "var(--color-kind-semantic)";
    case "episodic": return "var(--color-kind-episodic)";
    case "procedural": return "var(--color-kind-procedural)";
  }
}

export function MemoryGalaxy({ recalledTurn = 5 }: MemoryGalaxyProps) {
  const turnLabel = useMemo(
    () => `recalled · turn ${String(recalledTurn).padStart(2, "0")}`,
    [recalledTurn],
  );
  return (
    <svg
      viewBox="0 0 460 280"
      width="100%"
      height="100%"
      style={{ display: "block" }}
      aria-hidden
    >
      {LINKS.map(([a, b], i) => (
        <line
          key={i}
          x1={NODES[a].x}
          y1={NODES[a].y}
          x2={NODES[b].x}
          y2={NODES[b].y}
          stroke="rgba(255,255,255,0.08)"
          strokeWidth={1}
        />
      ))}
      {NODES.map((n, i) => (
        <g key={i}>
          <circle cx={n.x} cy={n.y} r={n.r * 2.5} fill={colourFor(n.kind)} opacity={0.12} />
          <circle cx={n.x} cy={n.y} r={n.r} fill={colourFor(n.kind)} />
        </g>
      ))}
      {/* Amber dashed highlight ring around the recently-recalled cluster. */}
      <circle
        cx={200}
        cy={80}
        r={22}
        fill="none"
        stroke="var(--color-accent)"
        strokeWidth={1}
        strokeDasharray="2 3"
      />
      <text
        x={227}
        y={78}
        fontSize={9}
        fontFamily="var(--font-mono)"
        fill="var(--color-accent)"
        style={{ letterSpacing: "0.04em", textTransform: "uppercase" }}
      >
        {turnLabel}
      </text>
    </svg>
  );
}
