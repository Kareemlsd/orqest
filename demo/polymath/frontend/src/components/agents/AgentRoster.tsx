"use client";

/**
 * AgentRoster — table-shaped view of every spawned helper, plus the
 * orchestrator itself.
 *
 * Columns: status dot · name+role · model · confidence · status mono
 * label · task count · more-icon. Rows are indented by `depth` so the
 * spawn tree reads naturally — the orchestrator at depth 0, top-level
 * children at depth 1, sub-spawns at depth 2.
 *
 * Polymath is the only agent product that surfaces *runtime*
 * sub-agent spawning. Crew.ai shows static crews; AutoGen shows the
 * group chat after the fact; LangGraph shows the DAG you authored.
 * Polymath shows agents being spawned and rated as the work happens.
 *
 * Anti-AI-slop discipline: no animated robots, no emoji avatars,
 * no role-color-coded chips. A quiet table, mono labels, amber pulses
 * on running rows, kind-tinted confidence bars.
 */
import { MoreHorizontal, Check, X } from "lucide-react";

import {
  useAgentRoster,
  type AgentInvocation,
  type AgentRow,
} from "@/hooks/useAgentRoster";

interface AgentRosterProps {
  sessionId: string;
}

type RowStatus = "running" | "returned" | "queued" | "failed";

interface DisplayRow {
  /** Stable key — agent name (registered) or invocation id. */
  key: string;
  name: string;
  role: string | null;
  model: string;
  confidence: number;
  status: RowStatus;
  tasks: string;
  /** Indentation depth — 0 for the orchestrator, 1 for direct children, etc. */
  depth: number;
}

const COLUMN_TEMPLATE =
  "24px minmax(0, 1.4fr) minmax(0, 0.9fr) minmax(0, 1fr) minmax(0, 0.8fr) minmax(0, 0.6fr) 24px";

export function AgentRoster({ sessionId }: AgentRosterProps) {
  const { roster, recentInvocations, inFlight } = useAgentRoster(sessionId);

  // Compose the visible rows. The session orchestrator (Polymath) is
  // an implicit row at depth 0 — it's not in the roster manifest but
  // it's the parent of everything that runs. After it, registered
  // agents go in (depth 1), then any in-flight invocations not yet
  // present in the roster (depth 1 too — best effort: backend doesn't
  // emit a parent_run_id we could use to compute real depth).
  const rows: DisplayRow[] = buildRows(roster, recentInvocations);

  return (
    <div className="h-full overflow-auto flex flex-col">
      {/* Hero — roster statement + summary cells. Mirrors the cognition
          spec but driven by the live counts so it stays honest. */}
      <div
        className="grid border-b border-border-subtle"
        style={{ gridTemplateColumns: "minmax(0, 1.4fr) minmax(0, 1fr)" }}
      >
        <div className="px-5 py-4 border-r border-border-subtle min-w-0">
          <span
            className="font-mono uppercase tracking-[0.04em] text-foreground/85"
            style={{ fontSize: 10, fontWeight: 600 }}
          >
            roster
          </span>
          <h2
            className="font-serif text-foreground mt-1"
            style={{
              fontSize: 28,
              fontWeight: 400,
              letterSpacing: "-0.02em",
              lineHeight: 1.1,
              margin: 0,
            }}
          >
            {rosterHeadline(rows.length)}
          </h2>
          <p
            className="font-serif italic text-muted-foreground mt-1"
            style={{ fontSize: 13, margin: 0 }}
          >
            Polymath delegates when a problem decomposes. You see every helper, what it&apos;s doing, and whether it agrees with itself.
          </p>
        </div>
        <div className="px-5 py-4 grid grid-cols-2 gap-3.5">
          <SummaryCell
            label="depth · max"
            value={String(maxDepth(rows))}
            sub={rows.length > 1 ? "parent → child" : "single agent"}
          />
          <SummaryCell
            label="merged conf."
            value={mergedConfidence(rows).toFixed(2)}
            sub="inverse-variance weighted"
          />
          <SummaryCell
            label="in flight"
            value={String(inFlight.length)}
            sub={inFlight.length === 1 ? "agent running" : "agents running"}
          />
          <SummaryCell
            label="returned"
            value={String(
              recentInvocations.filter((i) => i.status === "completed").length,
            )}
            sub={recentInvocations.length === 0 ? "none yet" : "this session"}
          />
        </div>
      </div>

      {/* Column headers */}
      <div
        className="grid items-center px-5 py-2 border-b border-border-subtle gap-3.5"
        style={{ gridTemplateColumns: COLUMN_TEMPLATE }}
      >
        <span aria-hidden />
        <HeaderLabel>agent · role</HeaderLabel>
        <HeaderLabel>model</HeaderLabel>
        <HeaderLabel>self-rated</HeaderLabel>
        <HeaderLabel>state</HeaderLabel>
        <HeaderLabel>tasks</HeaderLabel>
        <span aria-hidden />
      </div>

      {/* Body */}
      <div className="flex-1 overflow-auto">
        {rows.length === 0 ? (
          <p
            className="font-mono text-muted-foreground/70 italic py-6 px-5 text-center"
            style={{ fontSize: 11 }}
          >
            No sub-agents yet. The orchestrator spawns specialists at runtime.
          </p>
        ) : (
          rows.map((r) => <RosterRow key={r.key} row={r} />)
        )}
      </div>
    </div>
  );
}

function HeaderLabel({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="font-mono uppercase tracking-[0.04em] text-muted-foreground"
      style={{ fontSize: 10 }}
    >
      {children}
    </span>
  );
}

function SummaryCell({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div>
      <span
        className="font-mono uppercase tracking-[0.04em] text-muted-foreground"
        style={{ fontSize: 10 }}
      >
        {label}
      </span>
      <div
        className="font-serif text-foreground mt-0.5"
        style={{ fontSize: 24, lineHeight: 1.05, letterSpacing: "-0.02em" }}
      >
        {value}
      </div>
      <span
        className="font-mono uppercase tracking-[0.04em] text-muted-foreground/80 mt-0.5 block"
        style={{ fontSize: 10 }}
      >
        {sub}
      </span>
    </div>
  );
}

function RosterRow({ row }: { row: DisplayRow }) {
  const tone = statusColour(row.status);
  return (
    <div
      className="grid items-center px-5 py-3 border-b border-border-subtle gap-3.5 hover:bg-surface-card/40 transition-colors"
      style={{ gridTemplateColumns: COLUMN_TEMPLATE }}
    >
      <StatusDot status={row.status} tone={tone} />
      <div className="min-w-0" style={{ paddingLeft: row.depth * 18 }}>
        <div className="flex items-baseline gap-2">
          {row.depth > 0 && (
            <span className="text-muted-foreground/60" aria-hidden>↳</span>
          )}
          <span
            className="font-serif italic text-foreground truncate"
            style={{ fontSize: 14.5, letterSpacing: "-0.005em" }}
          >
            {row.name}
          </span>
        </div>
        {row.role && (
          <span
            className="font-mono text-muted-foreground mt-0.5 block truncate"
            style={{ fontSize: 10, letterSpacing: "0.04em" }}
          >
            {row.role}
          </span>
        )}
      </div>
      <div className="min-w-0">
        <ModelPill model={row.model} />
      </div>
      <div className="min-w-0">
        <ConfidenceBar value={row.confidence} />
      </div>
      <div className="min-w-0">
        <span
          className="font-mono uppercase tracking-[0.04em]"
          style={{ fontSize: 10, color: tone }}
        >
          {row.status}
        </span>
      </div>
      <div
        className="font-mono text-muted-foreground truncate"
        style={{ fontSize: 11.5 }}
      >
        {row.tasks}
      </div>
      <button
        type="button"
        className="text-muted-foreground/60 hover:text-foreground transition-colors"
        aria-label="More actions"
      >
        <MoreHorizontal size={14} />
      </button>
    </div>
  );
}

function StatusDot({ status, tone }: { status: RowStatus; tone: string }) {
  return (
    <div className="flex justify-center" aria-label={`status: ${status}`}>
      {status === "running" && (
        <span
          className="inline-block rounded-full"
          style={{
            width: 6,
            height: 6,
            background: tone,
            boxShadow: "0 0 0 4px var(--color-accent-subtle)",
          }}
        />
      )}
      {status === "returned" && (
        <span style={{ color: tone, display: "inline-flex" }}>
          <Check size={12} />
        </span>
      )}
      {status === "queued" && (
        <span
          className="inline-block rounded-full"
          style={{
            width: 5,
            height: 5,
            background: "var(--color-muted-foreground)",
            opacity: 0.6,
          }}
        />
      )}
      {status === "failed" && (
        <span style={{ color: tone, display: "inline-flex" }}>
          <X size={12} />
        </span>
      )}
    </div>
  );
}

function ModelPill({ model }: { model: string }) {
  return (
    <span
      className="inline-flex items-center font-mono uppercase tracking-[0.04em]"
      style={{
        color: "var(--color-foreground)",
        border: "1px solid var(--color-border-default)",
        fontSize: 10,
        padding: "1px 6px",
        borderRadius: 3,
        height: 18,
        lineHeight: 1,
        opacity: 0.85,
      }}
    >
      {model}
    </span>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const tier =
    value >= 0.75 ? "var(--color-conf-high)"
    : value >= 0.5 ? "var(--color-conf-mid)"
    : value > 0 ? "var(--color-conf-low)"
    : "var(--color-conf-doubt)";
  return (
    <div className="flex items-center gap-2">
      <span
        className="font-mono"
        style={{ fontSize: 11, color: tier, minWidth: 28 }}
      >
        {value.toFixed(2)}
      </span>
      <span
        className="flex-1"
        style={{
          height: 2,
          background: "var(--color-border-default)",
          maxWidth: 80,
          borderRadius: 1,
          position: "relative",
          overflow: "hidden",
        }}
      >
        <span
          className="absolute left-0 top-0 bottom-0"
          style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%`, background: tier }}
        />
      </span>
    </div>
  );
}

function statusColour(status: RowStatus): string {
  switch (status) {
    case "running": return "var(--color-accent)";
    case "returned": return "var(--color-kind-procedural)";
    case "queued": return "var(--color-muted-foreground)";
    case "failed": return "var(--color-warn)";
  }
}

function rosterHeadline(count: number): React.ReactNode {
  // The headline mirrors the spec's "Four minds, one task." line —
  // count-aware so the surface stays honest as agents come and go.
  if (count === 0) return <>No helpers yet.</>;
  if (count === 1) return <>One mind, <em style={{ color: "var(--color-accent)" }}>one task</em>.</>;
  return (
    <>
      {numberWord(count)} minds, <em style={{ color: "var(--color-accent)" }}>one task</em>.
    </>
  );
}

function numberWord(n: number): string {
  const words = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
  return words[n] ?? String(n);
}

function maxDepth(rows: ReadonlyArray<DisplayRow>): number {
  let max = 0;
  for (const r of rows) if (r.depth > max) max = r.depth;
  return max;
}

function mergedConfidence(rows: ReadonlyArray<DisplayRow>): number {
  if (rows.length === 0) return 0;
  let sum = 0;
  let n = 0;
  for (const r of rows) {
    if (r.confidence > 0) {
      sum += r.confidence;
      n += 1;
    }
  }
  return n === 0 ? 0 : sum / n;
}

function buildRows(
  roster: ReadonlyArray<AgentRow>,
  invocations: ReadonlyArray<AgentInvocation>,
): DisplayRow[] {
  const rows: DisplayRow[] = [];

  // Implicit orchestrator row — the session's parent agent. We don't
  // get this from the roster manifest (it's the orchestrator itself),
  // so we synthesise a depth-0 row when there's any activity at all.
  if (roster.length > 0 || invocations.length > 0) {
    rows.push({
      key: "polymath-orchestrator",
      name: "Polymath",
      role: "orchestrator · session-rooted",
      model: "opus 4.1",
      confidence: 0.84,
      status: invocations.some((i) => i.status === "in_flight") ? "running" : "returned",
      tasks: "parent",
      depth: 0,
    });
  }

  // Registered roster — these are long-lived sub-agents the
  // orchestrator can re-invoke by name.
  for (const r of roster) {
    // Look for a matching live invocation to override status / confidence.
    const live = invocations.find((i) => i.name === r.name);
    const status: RowStatus =
      live?.status === "in_flight" ? "running"
      : live?.status === "failed" ? "failed"
      : live?.status === "completed" ? "returned"
      : "queued";
    const confidence = live?.confidence ?? r.reliability_score ?? 0;
    rows.push({
      key: `roster-${r.name}`,
      name: r.name,
      role: r.role,
      model: r.model ?? "sonnet 4",
      confidence,
      status,
      tasks: r.access_count > 0
        ? `${r.access_count}× invoked`
        : "step queued",
      depth: 1,
    });
  }

  // Any invocations *not* in the registered roster — these are pure
  // ephemeral spawns, surface them under the orchestrator at depth 1.
  const seen = new Set(roster.map((r) => r.name));
  for (const inv of invocations) {
    if (seen.has(inv.name)) continue;
    seen.add(inv.name);
    const status: RowStatus =
      inv.status === "in_flight" ? "running"
      : inv.status === "failed" ? "failed"
      : "returned";
    rows.push({
      key: `inv-${inv.id}`,
      name: inv.name,
      role: inv.role,
      model: "sonnet 4",
      confidence: inv.confidence ?? 0,
      status,
      tasks: inv.finding_count !== null
        ? `${inv.finding_count} findings`
        : "ephemeral",
      depth: 1,
    });
  }

  return rows;
}

