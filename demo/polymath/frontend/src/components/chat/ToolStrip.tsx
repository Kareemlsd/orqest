"use client";

/**
 * ToolStrip — `<ChainOfThought>` adapter for assistant turns with two
 * or more tool calls.
 *
 * The single-tool-call path stays on `<ToolCard>`; this component is
 * mounted by `Message.tsx` only when the same assistant turn issued
 * `≥2` tool calls, so the busier-shaped chain-of-thought primitive only
 * shows up when it earns its keep.
 *
 * Each tool call lands as one `<ChainOfThoughtStep>`. The step's
 * `status` is derived from the part state (output-available → complete,
 * input-available / input-streaming → active, output-error → complete
 * with a destructive-tinted prefix; AI Elements' `ChainOfThoughtStep`
 * does not ship an explicit "error" status). The label is the tool
 * name; the description is a one-line summary derived from the part
 * input or output.
 *
 * Custom `toolRenderers[toolName]` outputs hang off the step body so
 * the existing built-in renderers (e.g. `web_search` → Sources)
 * continue to work inside the strip.
 */
import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtHeader,
  ChainOfThoughtStep,
} from "@/components/ai-elements/chain-of-thought";
import type { ToolPart, ToolRenderer } from "./ToolCard";

export interface ToolStripPart extends ToolPart {
  /** The tool name extracted from `part.type` (`tool-foo` → `foo`). */
  toolName: string;
}

interface ToolStripProps {
  toolParts: ToolStripPart[];
  toolRenderers: Record<string, ToolRenderer>;
  messageId: string;
}

export function ToolStrip({ toolParts, toolRenderers, messageId }: ToolStripProps) {
  if (toolParts.length === 0) return null;

  const headerLabel = `${toolParts.length} tools`;

  return (
    <div className="my-2">
      <ChainOfThought defaultOpen>
        <ChainOfThoughtHeader>{headerLabel}</ChainOfThoughtHeader>
        <ChainOfThoughtContent>
          {toolParts.map((part, idx) => {
            const status = stepStatus(part.state);
            const label = (
              <span className="flex items-center gap-2 font-mono text-[11px]">
                <span className={part.state === "output-error" ? "text-destructive" : "text-foreground"}>
                  {part.toolName}
                </span>
                <span className="text-muted-foreground">{part.state}</span>
              </span>
            );
            const description = summaryFor(part);
            const renderer = toolRenderers[part.toolName];
            return (
              <ChainOfThoughtStep
                description={description}
                key={`${messageId}-strip-${idx}`}
                label={label}
                status={status}
              >
                {renderer ? (
                  <div className="text-[13px] mt-1">{renderer(part)}</div>
                ) : null}
              </ChainOfThoughtStep>
            );
          })}
        </ChainOfThoughtContent>
      </ChainOfThought>
    </div>
  );
}

function stepStatus(state: ToolPart["state"]): "complete" | "active" | "pending" {
  if (state === "output-available") return "complete";
  if (state === "output-error") return "complete";
  if (state === "input-available" || state === "input-streaming") return "active";
  return "pending";
}

/**
 * Derive a short text summary for a single tool call. We try, in order:
 *   1. The first key + scalar value of the input (e.g. `query: "..."`)
 *   2. The first key + scalar value of the output
 *   3. `null` (no description rendered)
 */
function summaryFor(part: ToolPart): string | null {
  const fromInput = firstScalarSummary(part.input);
  if (fromInput) return fromInput;
  if (part.state === "output-available" && part.output) {
    const fromOutput = firstScalarSummary(part.output);
    if (fromOutput) return fromOutput;
  }
  return null;
}

const SCALAR_TRUNCATE = 80;

function firstScalarSummary(blob: unknown): string | null {
  if (!blob || typeof blob !== "object" || Array.isArray(blob)) return null;
  const obj = blob as Record<string, unknown>;
  for (const [key, value] of Object.entries(obj)) {
    if (value === null || value === undefined) continue;
    if (typeof value === "string") {
      return `${key}: ${truncate(value, SCALAR_TRUNCATE)}`;
    }
    if (typeof value === "number" || typeof value === "boolean") {
      return `${key}: ${value}`;
    }
  }
  return null;
}

function truncate(value: string, max: number): string {
  if (value.length <= max) return value;
  return value.slice(0, max - 1).trimEnd() + "…";
}
