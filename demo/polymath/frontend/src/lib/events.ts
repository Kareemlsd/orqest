/**
 * Typed `AgentEvent` mirror of `orqest.observability.AgentEvent`.
 *
 * Adds domain events emitted by polymath tools + backend infra:
 *   - plan.init / plan.task.updated
 *   - tool.web_search.started/completed, tool.web_fetch.started/completed
 *   - memory.stored / memory.recalled
 *   - Phase 2+: shell.stdout, browser.action, artifact.created, agent.spawned
 */

export type AgentEventType =
  | "heartbeat"
  | "plan.init"
  | "plan.task.updated"
  | "tool.before"
  | "tool.after"
  | "tool.web_search.started"
  | "tool.web_search.completed"
  | "tool.web_fetch.started"
  | "tool.web_fetch.completed"
  | "memory.stored"
  | "memory.recalled"
  | "shell.stdout"
  | "browser.action"
  | "artifact.created"
  | "agent.spawned"
  | "agent.completed";

export interface AgentEvent<T = Record<string, unknown>> {
  event_type: AgentEventType | string;
  agent_name: string;
  timestamp: string;
  data: T;
}

/**
 * Plan shape mirrored from `orqest.plan.ExecutionPlan.to_sse_init()`.
 * Backend canonical status strings are used verbatim: frontend rendering
 * layer maps them to dot colors.
 */
export type PlanStatus =
  | "pending"
  | "in-progress"
  | "completed"
  | "failed"
  | "skipped";

export interface PlanSubtask {
  id: string;
  title: string;
  description?: string;
  status: PlanStatus;
  priority?: "required" | "optional";
  tools?: string[];
}

export interface PlanTask {
  id: string;
  title: string;
  description?: string;
  status: PlanStatus;
  priority?: "required" | "optional";
  level?: number;
  dependencies?: string[];
  subtasks?: PlanSubtask[];
}

export interface Plan {
  tasks: PlanTask[];
}

export interface Artifact {
  id: string;
  kind: "chart" | "report" | "file" | string;
  mime: string;
  label: string;
  path: string;
  created_at: string;
}
