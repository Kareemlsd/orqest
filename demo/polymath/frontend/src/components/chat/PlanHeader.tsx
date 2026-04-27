"use client";

/**
 * PlanHeader — editorial checklist driven by `orqest.plan.ExecutionPlan`
 * state. Ported from `pm-screens.jsx:4-29`.
 *
 * Header layout:
 *   - Chevron + serif (Newsreader) title on the left
 *   - Right-aligned mono `4 of 7 · running` meta
 *
 * Each task row:
 *   - `NN` mono number column (zero-padded, two-digit)
 *   - Status icon: amber check (done) / amber pulse-dot (active /
 *     in-progress) / muted hollow circle (pending)
 *   - Sans 12.5px label, strikethrough + muted when done
 *   - Optional mono tool name pinned right
 *
 * Active items get an amber pulse-dot with a 3px amber-subtle box-shadow
 * ring — the design's only motion in this region.
 *
 * Populated by `usePlan(sessionId)` upstream — REST hydration on mount,
 * then SSE patches via legacy `plan.*` and typed `ui.plan.*` events.
 */
import { Check, ChevronDown } from "lucide-react";

import type { Plan, PlanStatus, PlanTask } from "@/lib/events";
import { cn } from "@/lib/utils";

interface PlanHeaderProps {
  plan: Plan;
}

export function PlanHeader({ plan }: PlanHeaderProps) {
  if (!plan.tasks.length) return null;

  const completed = plan.tasks.filter((t) => t.status === "completed").length;
  const total = plan.tasks.length;
  const isRunning = plan.tasks.some(
    (t) => t.status === "in-progress",
  );
  const meta = `${completed} of ${total} · ${isRunning ? "running" : "idle"}`;
  // The current `Plan` event shape doesn't carry a top-level title;
  // fall back to a serif "Plan" header. If a future schema bump
  // surfaces one, the loose access below picks it up.
  const titleField = (plan as unknown as { title?: unknown }).title;
  const title =
    typeof titleField === "string" && titleField.trim()
      ? titleField.trim()
      : "Plan";

  return (
    <div
      className="px-5 pt-3.5 pb-3"
      style={{ borderBottom: "1px solid var(--color-border-subtle)" }}
    >
      <div className="flex items-baseline gap-2 mb-2.5">
        <span style={{ color: "var(--color-muted-foreground)" }}>
          <ChevronDown className="size-3" />
        </span>
        <span
          className="font-serif text-[14px] tracking-tight text-foreground"
        >
          {title}
        </span>
        <div className="flex-1" />
        <span
          className="font-mono text-[10px] uppercase tracking-wide"
          style={{ color: "var(--color-muted-foreground)" }}
        >
          {meta}
        </span>
      </div>
      <div className="flex flex-col gap-1">
        {plan.tasks.map((task, i) => (
          <PlanRow
            key={task.id}
            num={String(i + 1).padStart(2, "0")}
            task={task}
          />
        ))}
      </div>
    </div>
  );
}

interface PlanRowProps {
  num: string;
  task: PlanTask;
}

function PlanRow({ num, task }: PlanRowProps) {
  const labelColor =
    task.status === "completed"
      ? "var(--color-muted-foreground)"
      : task.status === "in-progress"
        ? "var(--color-foreground)"
        : "var(--color-muted-foreground)";
  const tool = inferToolLabel(task);

  return (
    <div className="flex items-center gap-2.5 text-[12.5px]" style={{ color: labelColor }}>
      <span
        className="font-mono text-[10px] uppercase tracking-wide"
        style={{ color: "var(--color-muted-foreground)", opacity: 0.6, width: 18 }}
      >
        {num}
      </span>
      <StatusGlyph status={task.status} />
      <span
        className={cn(
          task.status === "completed" && "line-through",
        )}
        style={{
          textDecorationColor:
            task.status === "completed"
              ? "var(--color-border-default)"
              : undefined,
        }}
      >
        {task.title}
      </span>
      {tool && (
        <span
          className="ml-auto font-mono text-[10px] uppercase tracking-wide"
          style={{ color: "var(--color-muted-foreground)", opacity: 0.6 }}
        >
          {tool}
        </span>
      )}
    </div>
  );
}

function StatusGlyph({ status }: { status: PlanStatus }) {
  switch (status) {
    case "completed":
      return (
        <span
          className="inline-flex items-center justify-center"
          style={{ width: 14, color: "var(--color-accent)" }}
        >
          <Check className="size-3" />
        </span>
      );
    case "in-progress":
      return (
        <span
          className="inline-flex items-center justify-center"
          style={{ width: 14 }}
        >
          <span
            style={{
              width: 5,
              height: 5,
              borderRadius: "50%",
              background: "var(--color-accent)",
              boxShadow: "0 0 0 3px var(--color-accent-subtle)",
            }}
          />
        </span>
      );
    case "failed":
      return (
        <span
          className="inline-flex items-center justify-center"
          style={{ width: 14 }}
        >
          <span
            style={{
              width: 5,
              height: 5,
              borderRadius: "50%",
              background: "var(--color-destructive)",
              opacity: 0.85,
            }}
          />
        </span>
      );
    case "skipped":
    case "pending":
    default:
      return (
        <span
          className="inline-flex items-center justify-center"
          style={{ width: 14 }}
        >
          <span
            style={{
              width: 5,
              height: 5,
              borderRadius: "50%",
              background: "currentColor",
              opacity: 0.5,
            }}
          />
        </span>
      );
  }
}

/**
 * Best-effort inference of a tool name to surface on the right of a
 * task row. Reads the first subtask's first declared tool — the only
 * field on the current `PlanTask` schema that surfaces this hint.
 * Loose-typed fallbacks (`task.tool`, `task.metadata.tool`) catch
 * future schema additions without forcing a re-port.
 */
function inferToolLabel(task: PlanTask): string | undefined {
  const direct = (task as unknown as { tool?: unknown }).tool;
  if (typeof direct === "string" && direct.trim()) return direct.trim();
  const sub = task.subtasks?.[0];
  const subTool = sub?.tools?.[0];
  if (typeof subTool === "string" && subTool.trim()) return subTool.trim();
  const meta = (task as unknown as { metadata?: unknown }).metadata;
  if (meta && typeof meta === "object") {
    const t = (meta as Record<string, unknown>).tool;
    if (typeof t === "string" && t.trim()) return t.trim();
  }
  return undefined;
}
