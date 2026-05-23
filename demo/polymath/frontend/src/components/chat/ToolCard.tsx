"use client";

/**
 * ToolCard — left-stripe state indicator + spinner while streaming.
 *
 * Accepts a pluggable `toolRenderers` registry keyed by tool name.
 * Fallback is a `<pre>` JSON dump. Phase 0 ships an empty registry;
 * later phases wire `open_url`, `run_python_snippet`, `render_chart`,
 * `spawn_analyst`, etc.
 *
 * Built-in: `web_search` renders results as an AI Elements `<Sources>`
 * citation list when the output matches the `WebSearchResponse` shape.
 *
 * Errors render as a single muted line — `Tool {name} failed · {one
 * line message}` — with the warning accent on the left stripe and a
 * hover-revealed Retry action via the `Actions` primitive. Long error
 * messages get truncated to ~200 chars with the full text on the
 * `title` attribute. The Retry button is wired through the optional
 * `onRetry` prop; the visible affordance is the win — wiring can come
 * later without touching this file.
 */
import { ChevronRightIcon, RotateCcwIcon } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import { Actions, Action } from "@/components/ai-elements/actions";
import { Loader } from "@/components/ai-elements/loader";
import {
  Source,
  Sources,
  SourcesContent,
  SourcesTrigger,
} from "@/components/ai-elements/sources";
import { cn } from "@/lib/utils";

type ToolState =
  | "input-streaming"
  | "input-available"
  | "output-available"
  | "output-error";

export interface ToolPart {
  state: ToolState;
  input?: Record<string, unknown>;
  output?: unknown;
  errorText?: string;
}

export type ToolRenderer = (part: ToolPart) => ReactNode;

/**
 * Loose shape of `orqest.tools.web.WebSearchResponse`. Kept structural so
 * a backend version bump that adds optional fields doesn't break us.
 */
interface WebSearchResultLike {
  title?: unknown;
  url?: unknown;
  snippet?: unknown;
}
interface WebSearchResponseLike {
  results?: unknown;
}

function extractWebSearchResults(
  output: unknown,
): { title: string; url: string; snippet: string }[] | null {
  if (!output || typeof output !== "object") return null;
  const results = (output as WebSearchResponseLike).results;
  if (!Array.isArray(results)) return null;
  const cleaned: { title: string; url: string; snippet: string }[] = [];
  for (const r of results) {
    if (!r || typeof r !== "object") continue;
    const candidate = r as WebSearchResultLike;
    const url = typeof candidate.url === "string" ? candidate.url : "";
    if (!url) continue;
    cleaned.push({
      title:
        typeof candidate.title === "string" && candidate.title
          ? candidate.title
          : url,
      url,
      snippet:
        typeof candidate.snippet === "string" ? candidate.snippet : "",
    });
  }
  return cleaned.length > 0 ? cleaned : null;
}

/**
 * Built-in renderer for `web_search`: gracefully falls back to JSON when
 * the output shape doesn't match `WebSearchResponse`.
 */
export const webSearchRenderer: ToolRenderer = (part) => {
  if (part.state !== "output-available") return renderFallback(part);
  const sources = extractWebSearchResults(part.output);
  if (!sources) return renderFallback(part);
  return (
    <Sources>
      <SourcesTrigger count={sources.length} />
      <SourcesContent>
        {sources.map((s) => (
          <Source key={s.url} href={s.url} title={s.title} />
        ))}
      </SourcesContent>
    </Sources>
  );
};

interface ToolCardProps {
  toolName: string;
  part: ToolPart;
  toolRenderers: Record<string, ToolRenderer>;
  /** Optional retry callback wired by parent. The hover-revealed
   *  `Retry` action is rendered regardless — we want the affordance
   *  visible even before the wiring lands. */
  onRetry?: (toolName: string, part: ToolPart) => void;
}

// Built-in renderers — merged under user-supplied ones so consumers can
// still override (e.g. swap `web_search` for a Polymath-specific view).
const BUILTIN_RENDERERS: Record<string, ToolRenderer> = {
  web_search: webSearchRenderer,
};

const ERROR_TRUNCATE = 200;

export function ToolCard({ toolName, part, toolRenderers, onRetry }: ToolCardProps) {
  const renderer = toolRenderers[toolName] ?? BUILTIN_RENDERERS[toolName];
  const isError = part.state === "output-error";
  const stripeClass = isError
    ? "border-l-2 border-warning"
    : part.state === "input-streaming" ||
        part.state === "input-available" ||
        part.state === "output-available"
      ? "border-l-2 border-accent"
      : "border-l-2 border-neutral-700";

  // Auto-collapse 2s after a successful run completes; user can still
  // click the header to re-expand. Errors stay open. Manual expansion
  // sticks even if the same card transitions back to streaming.
  const [collapsed, setCollapsed] = useState(false);
  const [userToggled, setUserToggled] = useState(false);
  useEffect(() => {
    if (part.state !== "output-available" || userToggled) return;
    const t = setTimeout(() => setCollapsed(true), 2000);
    return () => clearTimeout(t);
  }, [part.state, userToggled]);

  // Errors render as a single muted line with hover-revealed retry —
  // skip the chrome of the standard tool-card entirely.
  if (isError) {
    return (
      <ErrorCard
        toolName={toolName}
        part={part}
        stripeClass={stripeClass}
        onRetry={onRetry}
      />
    );
  }

  const togglable = part.state === "output-available";

  return (
    <div
      className={cn(
        "group/tool my-2 rounded-md border border-border-default bg-surface-card overflow-hidden",
        stripeClass,
      )}
    >
      <button
        type="button"
        onClick={() => {
          if (!togglable) return;
          setUserToggled(true);
          setCollapsed((c) => !c);
        }}
        className={cn(
          "w-full flex items-center justify-between px-3 py-2 text-[11px] font-mono text-left",
          togglable && "hover:bg-surface-hover cursor-pointer",
        )}
      >
        <span className="flex items-center gap-1.5 text-foreground">
          {togglable && (
            <ChevronRightIcon
              className={cn(
                "size-3 text-muted-foreground transition-transform",
                !collapsed && "rotate-90",
              )}
            />
          )}
          {toolName}
        </span>
        <span className="text-muted-foreground">{part.state}</span>
      </button>
      {part.state === "input-streaming" && (
        <div className="flex items-center gap-2 px-3 py-1.5 border-t border-border-subtle bg-accent/5">
          <Loader size={12} />
          <span className="text-[11px] font-mono text-muted-foreground">
            streaming…
          </span>
        </div>
      )}
      {!collapsed && (
        <div className="p-3 text-[13px]">
          {renderer ? renderer(part) : renderFallback(part)}
        </div>
      )}
    </div>
  );
}

interface ErrorCardProps {
  toolName: string;
  part: ToolPart;
  stripeClass: string;
  onRetry?: (toolName: string, part: ToolPart) => void;
}

function ErrorCard({ toolName, part, stripeClass, onRetry }: ErrorCardProps) {
  const fullMessage = extractErrorMessage(part);
  const truncated =
    fullMessage.length > ERROR_TRUNCATE
      ? `${fullMessage.slice(0, ERROR_TRUNCATE).trimEnd()}…`
      : fullMessage;

  return (
    <div
      className={cn(
        "group/tool my-2 flex items-center gap-2 rounded-md border border-border-default bg-surface-card px-3 py-1.5",
        stripeClass,
      )}
    >
      <span
        className="flex-1 truncate font-mono text-[11px] text-muted-foreground"
        title={fullMessage}
      >
        Tool <span className="text-foreground">{toolName}</span> failed
        {truncated && (
          <>
            {" "}
            <span className="text-muted-foreground/70">·</span>{" "}
            {truncated}
          </>
        )}
      </span>
      <Actions>
        <Action
          label="Retry"
          onClick={() => onRetry?.(toolName, part)}
          disabled={!onRetry}
        >
          <RotateCcwIcon className="size-3" />
        </Action>
      </Actions>
    </div>
  );
}

/**
 * Best-effort one-line summary of a tool error. Pydantic-AI's error
 * shape is loose (sometimes a string, sometimes a structured dict on
 * `output`, sometimes both) — this helper picks the most informative
 * field available without throwing.
 */
function extractErrorMessage(part: ToolPart): string {
  if (typeof part.errorText === "string" && part.errorText.trim()) {
    return part.errorText.trim().split("\n")[0].trim();
  }
  if (typeof part.output === "string" && part.output.trim()) {
    return part.output.trim().split("\n")[0].trim();
  }
  if (part.output && typeof part.output === "object") {
    const obj = part.output as Record<string, unknown>;
    for (const key of ["error", "message", "detail", "reason"]) {
      const val = obj[key];
      if (typeof val === "string" && val.trim()) {
        return val.trim().split("\n")[0].trim();
      }
    }
  }
  return "unknown error";
}

function renderFallback(part: ToolPart) {
  const data =
    part.state === "output-error"
      ? part.errorText
      : part.output ?? part.input;
  if (data === undefined || data === null) return null;
  const text = typeof data === "string" ? data : JSON.stringify(data, null, 2);
  return (
    <pre className="whitespace-pre-wrap break-words font-mono text-[11px] text-muted-foreground">
      {text}
    </pre>
  );
}
