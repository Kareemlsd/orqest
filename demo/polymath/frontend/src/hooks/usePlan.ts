"use client";

/**
 * usePlan — keeps the session's live plan in sync.
 *
 * On mount: GET /sessions/{sid}/plan (hydrates any plan already reconstructed
 * from the event ring buffer).
 *
 * Subscribes to BOTH the legacy and typed-UI event streams (Phase β.3 dual
 * emission, Phase γ.9 typed-UI consumer):
 *
 * - Legacy: `plan.init` (replace) + `plan.task.updated` (per-task patch).
 * - Typed:  `ui.plan.init` (PlanComponent envelope) + `ui.plan.delta`
 *           (UIDeltaEvent with dot-path patches). Mirrors `orqest.ui.spec`.
 *
 * Both paths are kept active so this hook works against any backend version.
 * Hydration order: REST fetch first (mount fallback) → SSE handlers patch on
 * top as events arrive.
 */
import { useEffect, useState } from "react";

import { backendBase } from "@/lib/api";
import type { Plan, PlanStatus, PlanSubtask, PlanTask } from "@/lib/events";
import { useSidecar } from "./useSidecar";

const EMPTY_PLAN: Plan = { tasks: [] };

/**
 * Mirrors `orqest.ui.spec.UIDeltaEvent`. Values are unknown until the dot-path
 * is matched and validated against the local plan shape.
 */
interface UIDeltaEvent {
  op: "replace" | "merge" | "append" | "remove";
  path: string;
  value: unknown;
  component_id: string;
  component_type: string;
}

/**
 * `ui.plan.init` payload mirrors `PlanComponent` (`UIComponentSpec[PlanComponentData]`):
 * `{ component_type: "plan", component_id, data: { tasks: [...] }, metadata, created_at }`.
 * We only consume `data` for state replacement — the rest is metadata for routing.
 */
interface PlanComponentEnvelope {
  component_type: "plan";
  component_id: string;
  data: { tasks?: PlanTask[] };
}

export function usePlan(sessionId: string): { plan: Plan } {
  const [plan, setPlan] = useState<Plan>(EMPTY_PLAN);

  // Hydrate from the backend's plan reconstruction on mount.
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(`${backendBase()}/sessions/${sessionId}/plan`);
        if (!resp.ok) return;
        const data = (await resp.json()) as Plan;
        if (!cancelled) setPlan(data);
      } catch {
        // Silent — SSE will populate once events arrive.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // Subscribe to live events (legacy + typed UI in parallel).
  useSidecar(sessionId, (evt) => {
    // --- Legacy plan events (pre-Phase-β backends) ---------------------
    if (evt.event_type === "plan.init") {
      const tasks = (evt.data as { tasks?: PlanTask[] }).tasks ?? [];
      setPlan({ tasks });
      return;
    }
    if (evt.event_type === "plan.task.updated") {
      const { task_id, subtask_id, status } = evt.data as {
        task_id?: string;
        subtask_id?: string | null;
        status?: PlanStatus;
      };
      if (!task_id || !status) return;
      setPlan((prev) => patchTaskStatus(prev, task_id, status, subtask_id));
      return;
    }
    // --- Typed UI events (Phase β.3 dual emission) ---------------------
    if (evt.event_type === "ui.plan.init") {
      const envelope = evt.data as unknown as PlanComponentEnvelope;
      const tasks = envelope?.data?.tasks ?? [];
      setPlan({ tasks });
      return;
    }
    if (evt.event_type === "ui.plan.delta") {
      const delta = evt.data as unknown as UIDeltaEvent;
      setPlan((prev) => applyDelta(prev, delta));
      return;
    }
  });

  return { plan };
}

function patchTaskStatus(
  plan: Plan,
  taskId: string,
  status: PlanStatus,
  subtaskId: string | null | undefined,
): Plan {
  return {
    tasks: plan.tasks.map((t) => {
      if (t.id !== taskId) return t;
      if (subtaskId) {
        return {
          ...t,
          subtasks: (t.subtasks ?? []).map((s): PlanSubtask =>
            s.id === subtaskId ? { ...s, status } : s,
          ),
        };
      }
      return { ...t, status };
    }),
  };
}

/**
 * Apply a `UIDeltaEvent` to a plan. Pure / immutable — returns a new `Plan`.
 *
 * Today the backend only emits `op: "replace"` for status fields. Recognised
 * paths:
 *   - `tasks.<i>.status`
 *   - `tasks.<i>.subtasks.<j>.status`
 *
 * Any other path or op is logged at debug level and ignored. Out-of-range
 * indices are also no-ops.
 */
function applyDelta(plan: Plan, delta: UIDeltaEvent): Plan {
  if (delta.op !== "replace") {
    if (typeof console !== "undefined") {
      console.debug(
        "[usePlan] unhandled UIDeltaEvent op",
        delta.op,
        delta.path,
      );
    }
    return plan;
  }

  const segments = delta.path.split(".");
  // tasks.<i>.status
  if (segments.length === 3 && segments[0] === "tasks" && segments[2] === "status") {
    const idx = Number.parseInt(segments[1], 10);
    if (!Number.isFinite(idx) || idx < 0 || idx >= plan.tasks.length) return plan;
    const status = delta.value as PlanStatus;
    return {
      tasks: plan.tasks.map((t, i) => (i === idx ? { ...t, status } : t)),
    };
  }
  // tasks.<i>.subtasks.<j>.status
  if (
    segments.length === 5 &&
    segments[0] === "tasks" &&
    segments[2] === "subtasks" &&
    segments[4] === "status"
  ) {
    const ti = Number.parseInt(segments[1], 10);
    const sj = Number.parseInt(segments[3], 10);
    if (!Number.isFinite(ti) || ti < 0 || ti >= plan.tasks.length) return plan;
    const target = plan.tasks[ti];
    const subs = target.subtasks ?? [];
    if (!Number.isFinite(sj) || sj < 0 || sj >= subs.length) return plan;
    const status = delta.value as PlanStatus;
    return {
      tasks: plan.tasks.map((t, i) => {
        if (i !== ti) return t;
        return {
          ...t,
          subtasks: (t.subtasks ?? []).map((s, j): PlanSubtask =>
            j === sj ? { ...s, status } : s,
          ),
        };
      }),
    };
  }

  if (typeof console !== "undefined") {
    console.debug("[usePlan] unhandled UIDeltaEvent path", delta.path);
  }
  return plan;
}
