"use client";

/**
 * useCognitiveGutterEvents — derives the `events` array consumed by
 * `<CognitiveGutter>` for a given assistant message.
 *
 * MVP strategy: walk the message's own `parts` and emit one tick per
 * tool-* part, evenly spaced along the `0..1` axis. This trades the
 * fidelity of "exact wall-clock placement" for the simplicity of "no
 * SSE wiring required" — the gutter still tells the user *what* the
 * agent reached for and *in what order*, which is the load-bearing
 * signal.
 *
 * Future iterations can subscribe to the event bus via `useSidecar`
 * and bucket events into the assistant turn's window for true
 * time-positioned ticks. For now we stay in the message's own data.
 *
 * Tool-* parts whose `.output` shape exposes a memory hint (e.g. a
 * `memory_type` field) project as `kind: 'memory'`; spawned-sub-agent
 * parts (heuristic: tool name contains `spawn` or `agent`) project as
 * `kind: 'sub'`; everything else is `kind: 'tool'`.
 */
import { useMemo } from "react";
import type { UIMessage } from "ai";

import type { CognitiveEvent } from "@/components/chat/CognitiveGutter";

interface ToolPartLike {
  type?: unknown;
  output?: unknown;
}

function isToolPart(part: unknown): part is ToolPartLike {
  return (
    typeof part === "object" &&
    part !== null &&
    typeof (part as { type?: unknown }).type === "string" &&
    ((part as { type: string }).type).startsWith("tool-")
  );
}

/**
 * Pick a kind for a tool-* part. Heuristics in priority order:
 *
 *   1. Output looks like a memory record → `memory`.
 *   2. Tool name contains `spawn` or `agent` (sub-agent dispatch) → `sub`.
 *   3. Otherwise → `tool`.
 */
function kindForToolPart(toolName: string, output: unknown): CognitiveEvent["kind"] {
  if (
    output &&
    typeof output === "object" &&
    typeof (output as { memory_type?: unknown }).memory_type === "string"
  ) {
    return "memory";
  }
  const lower = toolName.toLowerCase();
  if (lower.includes("spawn") || lower.includes("sub_agent") || lower.includes("subagent")) {
    return "sub";
  }
  return "tool";
}

/**
 * Public hook signature. `sessionId` is accepted for parity with the
 * spec but is unused at MVP — kept so future SSE-aware revisions are
 * a non-breaking expansion.
 */
export function useCognitiveGutterEvents(
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  sessionId: string,
  message: UIMessage,
): CognitiveEvent[] {
  return useMemo<CognitiveEvent[]>(() => {
    const parts = message.parts ?? [];
    const ticks: CognitiveEvent[] = [];

    // First pass: collect tool-* parts in source order.
    const tools: { toolName: string; output: unknown }[] = [];
    for (const part of parts) {
      if (!isToolPart(part)) continue;
      const toolName = (part.type as string).slice(5);
      tools.push({ toolName, output: part.output });
    }
    if (tools.length === 0) return ticks;

    // Spread ticks evenly along `0..1`. With one tool we anchor at the
    // mid-point so the lonely tick doesn't crowd the live pulse at the
    // bottom or the (potential) live edge at the top. With more we
    // walk the interior of the axis, leaving margin at both ends.
    if (tools.length === 1) {
      const { toolName, output } = tools[0];
      ticks.push({
        at: 0.5,
        kind: kindForToolPart(toolName, output),
        label: toolName,
      });
      return ticks;
    }

    const margin = 0.08;
    const span = 1 - margin * 2;
    for (let i = 0; i < tools.length; i++) {
      const { toolName, output } = tools[i];
      const at = margin + (span * i) / (tools.length - 1);
      ticks.push({
        at,
        kind: kindForToolPart(toolName, output),
        label: toolName,
      });
    }

    return ticks;
  }, [message]);
}
