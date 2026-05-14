/**
 * Shared AgentEvent type for the Orqest SSE sidecar.
 *
 * Mirrors the backend `orqest.observability.events.AgentEvent` Pydantic
 * shape. All Orqest cognitive-backbone events (tool.*, metacognition.*,
 * healing.*, ui.*, plan.*, discovery.*, memory.*) conform to this shape.
 */

export interface AgentEvent {
  /** `<subsystem>.<event>[.<detail>]` — e.g. `metacognition.confidence`, `ui.chart.init`. */
  event_type: string;
  /** Source agent name; useful for filtering multi-agent runs. */
  agent_name: string;
  /** ISO 8601 UTC timestamp string. */
  timestamp: string;
  /** Free-form payload. Shape depends on `event_type`. */
  data: Record<string, unknown>;
  /** Set when the event was emitted from inside a traced span. */
  span_id?: string;
  /** Set when the event participates in a trace. */
  trace_id?: string;
}
