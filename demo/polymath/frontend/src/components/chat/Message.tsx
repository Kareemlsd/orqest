"use client";

/**
 * Role-aware message wrapper. Wraps each message in the AI Elements
 * `<Message from="…">` primitive (which sets a `group` class on the
 * outer `<div>` for hover-reveal patterns).
 *
 * Assistant messages now render as a flex row with a `<CognitiveGutter>`
 * left rail (24px) + a body column. Confidence is no longer surfaced
 * as a numeric pill in the header; it's height-encoded in the gutter
 * bar's fill. The header line carries the editorial masthead instead
 * — `POLYMATH · TURN NN  ·  HH:MM:SS  ·  tools` (mono 10px uppercase).
 *
 * The per-turn metadata strip ('confidence · 0.78 · tools · … · N
 * sources · ⌘+r retry · ⌘+f fork · ⌘+m memorize') sits as a footer
 * line on the assistant block — top dashed border, 10px mono content,
 * right-aligned kbd hints.
 *
 * User messages are tighter: no bubble background, just a right-aligned
 * card-surface block with a left-edge `border-l-2 border-border-default`
 * accent.
 *
 * Inherits design from numatics-ai ChatV3Panel refs 1 + 11.
 */
import { memo, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { CopyIcon, RefreshCcwIcon } from "lucide-react";
import type { UIMessage } from "ai";
import type { BundledLanguage } from "shiki";

import { Action, Actions } from "@/components/ai-elements/actions";
import {
  CodeBlock,
  CodeBlockCopyButton,
  CodeBlockFilename,
  CodeBlockHeader,
  CodeBlockTitle,
} from "@/components/ai-elements/code-block";
import { Message as ElementMessage } from "@/components/ai-elements/message";
import {
  Reasoning,
  ReasoningContent,
  ReasoningTrigger,
} from "@/components/ai-elements/reasoning";
import type { MetacognitionFrame } from "@/hooks/useMetacognition";
import type { ChatTurnMetrics } from "@/hooks/useChatMetrics";
import { useCognitiveGutterEvents } from "@/hooks/useCognitiveGutterEvents";

import { CognitiveGutter } from "./CognitiveGutter";
import {
  collectWebSearchResults,
  renderInlineCitationsAndSources,
  type WebSearchResult,
} from "./Sources";
import type { ToolPart, ToolRenderer } from "./ToolCard";
import { ToolCard } from "./ToolCard";
import { ToolStrip, type ToolStripPart } from "./ToolStrip";

interface MessageProps {
  /** Session id — flows through to the gutter events hook for future
   *  SSE-backed positioning. Currently unused at the hook level. */
  sessionId: string;
  message: UIMessage;
  /** Index of this message in the full transcript — drives the
   *  `TURN NN` masthead label. Two-digit zero-padded. */
  turnIndex: number;
  toolRenderers: Record<string, ToolRenderer>;
  /** Frozen metacognition frame for this assistant message — drives
   *  the cognitive gutter's confidence-bar height + color. `null`
   *  for user messages or assistant messages whose tool calls didn't
   *  return an `EnrichedOutput`. */
  metacognition?: MetacognitionFrame | null;
  /** Frozen per-turn metrics from the `chat.turn.completed` event.
   *  `null` while the turn is still in flight or for cached/historical
   *  messages that pre-date the event stream. */
  metrics?: ChatTurnMetrics | null;
  /** True while this message is the actively streaming one — drives
   *  the gutter's amber pulse at the bottom. */
  isStreaming?: boolean;
  /** Optional callback invoked when the user clicks the hover-revealed
   *  Regenerate action. Wired from `ChatPane` to either `useChat`'s
   *  `regenerate()` or a `sendMessage` of the prior user prompt. */
  onRegenerate?: (messageId: string) => void;
}

// AI SDK v6 reasoning part shape (kept loose — pydantic-ai may emit
// `state` as "streaming" | "done" or `text` field name varies).
interface ReasoningPart {
  type: "reasoning";
  text?: string;
  state?: "streaming" | "done" | string;
}

function isReasoningPart(part: unknown): part is ReasoningPart {
  return (
    typeof part === "object" &&
    part !== null &&
    (part as { type?: string }).type === "reasoning"
  );
}

interface TextPart {
  type: "text";
  text?: string;
}

function isTextPart(part: unknown): part is TextPart {
  return (
    typeof part === "object" &&
    part !== null &&
    (part as { type?: string }).type === "text"
  );
}

/**
 * `ChatMessage` is wrapped in `React.memo` (see export below) so a
 * streaming token landing on the latest assistant message doesn't
 * re-render every previous message. Memoisation only pays off if the
 * inputs are reference-stable for messages that haven't changed.
 */
function ChatMessageImpl({
  sessionId,
  message,
  turnIndex,
  toolRenderers,
  metacognition,
  metrics,
  isStreaming = false,
  onRegenerate,
}: MessageProps) {
  const isUser = message.role === "user";

  // Walk parts once: collect the text body (for clipboard copy) and
  // the deduped list of web-search results (for inline citations) in
  // the same pass.
  const { renderables, plainText, toolNames, sourceCount } = useMemo(
    () => buildRenderables(message, toolRenderers),
    [message, toolRenderers],
  );

  // Derive the gutter event ticks from the message's parts. Hook
  // result is already memoised; passes a stable reference to the
  // gutter so React.memo holds across token ticks.
  const gutterEvents = useCognitiveGutterEvents(sessionId, message);

  // Editorial header bits.
  const turnLabel = useMemo(
    () => `POLYMATH · TURN ${String(turnIndex).padStart(2, "0")}`,
    [turnIndex],
  );
  const timestampLabel = useMemo(
    () => formatTimestamp(message.metadata),
    [message.metadata],
  );
  const toolHeaderLabel = useMemo(() => {
    if (toolNames.length === 0) return null;
    // Dedupe + cap. The header is a one-liner; with > 3 distinct tools
    // we summarise as the first few + a trailing `…` so the line stays
    // tight and the full breakdown lives in the footer strip.
    const distinct: string[] = [];
    for (const name of toolNames) {
      if (!distinct.includes(name)) distinct.push(name);
      if (distinct.length === 3) break;
    }
    const more = toolNames.length > distinct.length;
    return more ? `${distinct.join(" · ")} · …` : distinct.join(" · ");
  }, [toolNames]);

  if (isUser) {
    return (
      <ElementMessage from={message.role} className="items-end">
        <div className="ml-auto max-w-[78%] rounded-md border border-border-default border-l-2 bg-card px-3 py-2 text-[14px] text-foreground">
          {renderables}
        </div>
      </ElementMessage>
    );
  }

  return (
    <ElementMessage from={message.role}>
      <div className="flex gap-0 w-full">
        <CognitiveGutter
          confidence={metacognition?.confidence ?? null}
          events={gutterEvents}
          live={isStreaming}
        />
        <div className="flex-1 min-w-0 pl-3.5">
          {/* Editorial role-label row. Replaces the earlier inline
              `<ConfidenceBadge>`-on-right header — confidence now flows
              through the gutter's height-encoded bar. */}
          <div className="flex items-baseline gap-2 mb-2">
            <span
              className="font-mono text-[10px] font-semibold uppercase tracking-wide"
              style={{ color: "var(--color-muted-foreground)" }}
            >
              {turnLabel}
            </span>
            <span
              className="font-mono text-[10px] uppercase tracking-wide"
              style={{ color: "var(--color-muted-foreground)", opacity: 0.7 }}
            >
              · {timestampLabel}
            </span>
            {toolHeaderLabel && (
              <span
                className="font-mono text-[10px] uppercase tracking-wide"
                style={{ color: "var(--color-muted-foreground)", opacity: 0.7 }}
              >
                · {toolHeaderLabel}
              </span>
            )}
          </div>
          {/* Body */}
          <div className="text-[14px] leading-relaxed text-foreground">
            {renderables}
          </div>
          {/* Per-turn metadata strip — moved from below body into the
              assistant block's own footer line. */}
          {(metacognition || metrics) && (
            <FooterStrip
              metacognition={metacognition ?? null}
              metrics={metrics ?? null}
              sourceCount={sourceCount}
            />
          )}
          {/* Hover-revealed Actions row */}
          <Actions className="pl-1.5">
            <Action
              label="Copy"
              onClick={() => {
                if (typeof navigator !== "undefined" && navigator.clipboard) {
                  void navigator.clipboard.writeText(plainText);
                }
              }}
            >
              <CopyIcon className="size-3" />
            </Action>
            <Action
              label="Regenerate"
              onClick={() => onRegenerate?.(message.id)}
              disabled={!onRegenerate}
            >
              <RefreshCcwIcon className="size-3" />
            </Action>
          </Actions>
        </div>
      </div>
    </ElementMessage>
  );
}

/**
 * Memoised export — shallow-compares all props. Stable inputs are an
 * upstream contract: `ChatPane` freezes the renderer registry and
 * accessor identities, AI SDK v6 keeps past message references intact.
 */
export const ChatMessage = memo(ChatMessageImpl);
ChatMessage.displayName = "ChatMessage";

interface FooterStripProps {
  metacognition: MetacognitionFrame | null;
  metrics: ChatTurnMetrics | null;
  sourceCount: number;
}

/**
 * Renders the bottom dashed-divider footer line. Mirror of the design's
 * `Turn` block (lines 274-291): mono 10px content with `confidence ·
 * 0.78`, `tools · …`, `N sources`, plus a right-aligned mono kbd hint
 * `⌘+r retry · ⌘+f fork · ⌘+m memorize`.
 */
function FooterStrip({
  metacognition,
  metrics,
  sourceCount,
}: FooterStripProps) {
  const confidence = metacognition?.confidence ?? null;
  const confColor =
    confidence === null
      ? "var(--color-muted-foreground)"
      : confidence >= 0.85
        ? "var(--color-conf-high)"
        : confidence >= 0.65
          ? "var(--color-conf-mid)"
          : confidence >= 0.45
            ? "var(--color-conf-low)"
            : "var(--color-conf-doubt)";

  return (
    <div
      className="flex items-center gap-3 mt-3 pt-2.5 font-mono text-[10px] uppercase tracking-wide"
      style={{
        borderTop: "1px dashed var(--color-border-subtle)",
        color: "var(--color-muted-foreground)",
      }}
    >
      {confidence !== null && (
        <div className="flex items-center gap-1.5">
          <span style={{ color: "var(--color-muted-foreground)" }}>conf</span>
          <span
            className="font-mono text-[11px] normal-case"
            style={{ color: confColor }}
          >
            {confidence.toFixed(2)}
          </span>
          <span
            className="relative inline-block"
            style={{
              width: 60,
              height: 2,
              background: "var(--color-border-default)",
              borderRadius: 1,
            }}
          >
            <span
              className="absolute left-0 top-0 bottom-0"
              style={{
                width: `${Math.max(2, confidence * 100)}%`,
                background: confColor,
              }}
            />
          </span>
        </div>
      )}
      {metrics && metrics.toolCalls > 0 && (
        <span>
          tools ·{" "}
          {metrics.toolCalls === 1 ? "1 tool" : `${metrics.toolCalls} tools`}
        </span>
      )}
      {metrics && metrics.durationMs > 0 && (
        <span>{(metrics.durationMs / 1000).toFixed(1)}s</span>
      )}
      {metrics && metrics.totalTokens > 0 && (
        <span>{formatTokens(metrics.totalTokens)} tokens</span>
      )}
      {sourceCount > 0 && (
        <span>
          {sourceCount === 1 ? "1 source" : `${sourceCount} sources`}
        </span>
      )}
      <div className="flex-1" />
      <span style={{ color: "var(--color-muted-foreground)", opacity: 0.6 }}>
        ⌘+r retry · ⌘+f fork · ⌘+m memorize
      </span>
    </div>
  );
}

interface BuildResult {
  renderables: React.ReactNode[];
  /** Concatenated plain-text payload across all `text` parts — handy
   *  for the Copy action without re-walking. */
  plainText: string;
  /** Tool names in source order — fed to the editorial header line. */
  toolNames: string[];
  /** How many distinct web-search sources surfaced — fed to the
   *  footer strip's "N sources" label. */
  sourceCount: number;
}

function buildRenderables(
  message: UIMessage,
  toolRenderers: Record<string, ToolRenderer>,
): BuildResult {
  const parts = message.parts ?? [];
  const renderables: React.ReactNode[] = [];
  const textChunks: string[] = [];
  const toolNames: string[] = [];
  // Sources (web_search results) live in tool-* parts; collect them
  // once so each text part can resolve `[N]` markers cheaply.
  const sources: WebSearchResult[] = collectWebSearchResults(parts);
  let trayRendered = false;

  // Pre-count tool-* parts. With ≥2 in the same assistant turn we
  // render the whole batch as a single `<ToolStrip>`
  // (`<ChainOfThought>`-backed) at the position of the first tool-*
  // part instead of stacking individual `<ToolCard>`s.
  const toolPartCount = countToolParts(parts);
  const useStrip = toolPartCount >= 2;
  let stripRendered = false;

  let i = 0;
  while (i < parts.length) {
    const part = parts[i];
    const key = `${message.id}-${i}`;

    if (isReasoningPart(part)) {
      const buffer: ReasoningPart[] = [part];
      let j = i + 1;
      while (j < parts.length && isReasoningPart(parts[j])) {
        buffer.push(parts[j] as ReasoningPart);
        j++;
      }
      const isStreaming = buffer.some((p) => p.state === "streaming");
      const text = buffer.map((p) => p.text ?? "").join("\n");
      renderables.push(
        <Reasoning key={key} isStreaming={isStreaming} summary={true}>
          <ReasoningTrigger />
          <ReasoningContent>{text}</ReasoningContent>
        </Reasoning>,
      );
      i = j;
      continue;
    }

    if (isTextPart(part)) {
      const raw = part.text ?? "";
      textChunks.push(raw);
      const { textWithCitations, sourcesNode } = renderInlineCitationsAndSources(
        raw,
        sources,
      );
      renderables.push(
        <div key={key} className="prose-polymath">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={makeMarkdownComponents(textWithCitations, raw)}
          >
            {raw}
          </ReactMarkdown>
        </div>,
      );
      if (sourcesNode && !trayRendered) {
        renderables.push(<div key={`${key}-sources`}>{sourcesNode}</div>);
        trayRendered = true;
      }
    } else if (
      typeof part.type === "string" &&
      part.type.startsWith("tool-")
    ) {
      const toolName = part.type.slice(5);
      toolNames.push(toolName);
      if (useStrip) {
        if (!stripRendered) {
          const toolPartsForStrip = collectToolStripParts(parts);
          renderables.push(
            <ToolStrip
              key={`${message.id}-toolstrip`}
              messageId={message.id}
              toolParts={toolPartsForStrip}
              toolRenderers={toolRenderers}
            />,
          );
          stripRendered = true;
        }
      } else {
        renderables.push(
          <ToolCard
            key={key}
            toolName={toolName}
            part={part as never}
            toolRenderers={toolRenderers}
          />,
        );
      }
    }
    i++;
  }
  return {
    renderables,
    plainText: textChunks.join("\n\n"),
    toolNames,
    sourceCount: sources.length,
  };
}

/**
 * Count the tool-* parts in a message's parts array. Used to decide
 * single-card vs. ChainOfThought-backed-strip rendering for an
 * assistant turn (Stream 3 / Step 8).
 */
function countToolParts(parts: ReadonlyArray<unknown>): number {
  let n = 0;
  for (const part of parts) {
    if (
      typeof part === "object" &&
      part !== null &&
      typeof (part as { type?: unknown }).type === "string" &&
      ((part as { type: string }).type).startsWith("tool-")
    ) {
      n++;
    }
  }
  return n;
}

/**
 * Project the tool-* parts of a message into the shape `<ToolStrip>`
 * expects: each carries the resolved `toolName` (suffix of `tool-*`)
 * alongside the original `state` / `input` / `output` / `errorText`
 * fields. Order is preserved.
 */
function collectToolStripParts(
  parts: ReadonlyArray<unknown>,
): ToolStripPart[] {
  const out: ToolStripPart[] = [];
  for (const part of parts) {
    if (
      typeof part === "object" &&
      part !== null &&
      typeof (part as { type?: unknown }).type === "string" &&
      ((part as { type: string }).type).startsWith("tool-")
    ) {
      const typed = part as { type: string } & ToolPart;
      out.push({
        ...typed,
        toolName: typed.type.slice(5),
      });
    }
  }
  return out;
}

/**
 * Format `message.metadata.createdAt` as `HH:MM:SS` for the editorial
 * masthead. Falls back to `now` when the metadata isn't present (e.g.
 * historical messages persisted without a timestamp).
 */
function formatTimestamp(metadata: unknown): string {
  if (metadata && typeof metadata === "object") {
    const m = metadata as Record<string, unknown>;
    const candidates = [m.createdAt, m.created_at, m.timestamp];
    for (const c of candidates) {
      if (typeof c === "string" || typeof c === "number") {
        const d = new Date(c);
        if (!Number.isNaN(d.getTime())) return formatHms(d);
      }
    }
  }
  return "now";
}

function formatHms(d: Date): string {
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

function formatTokens(n: number): string {
  if (n < 1000) return n.toString();
  if (n < 10_000) return `${(n / 1000).toFixed(1)}k`;
  return `${Math.round(n / 1000)}k`;
}

/**
 * Extract Shiki language id from react-markdown's `className`
 * (e.g. "language-python" → "python"). Defaults to "text".
 */
function extractLanguage(className: string | undefined): BundledLanguage {
  if (!className) return "text" as BundledLanguage;
  const match = /language-(\w+)/.exec(className);
  return (match?.[1] ?? "text") as BundledLanguage;
}

/**
 * Build the markdown component overrides for a single text part. We
 * splice the citation-resolved nodes into the `p` renderer when the
 * markdown emits the body's first paragraph that exactly matches the
 * raw text (i.e. no other markdown structure exists).
 */
function makeMarkdownComponents(
  citationNodes: React.ReactNode,
  rawText: string,
): Record<string, unknown> {
  const hasCitations = citationNodes !== rawText;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const overrides: Record<string, any> = { ...markdownComponents };

  if (hasCitations) {
    overrides.p = (
      props: React.HTMLAttributes<HTMLParagraphElement> & {
        children?: React.ReactNode;
      },
    ) => {
      const children = props.children;
      const single =
        typeof children === "string" && children.trim() === rawText.trim();
      return (
        <p className="my-1.5 leading-relaxed" {...props}>
          {single ? citationNodes : children}
        </p>
      );
    };
  }
  return overrides;
}

/**
 * Markdown renderer overrides — serif headings, tabular alternating rows,
 * no link underlines.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const markdownComponents: Record<string, any> = {
  h1: (props: React.HTMLAttributes<HTMLHeadingElement>) => (
    <h1 className="font-serif text-[18px] mt-3 mb-2" {...props} />
  ),
  h2: (props: React.HTMLAttributes<HTMLHeadingElement>) => (
    <h2 className="font-serif text-[18px] mt-3 mb-2" {...props} />
  ),
  h3: (props: React.HTMLAttributes<HTMLHeadingElement>) => (
    <h3 className="font-serif text-[15px] mt-2 mb-1.5" {...props} />
  ),
  a: (props: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a className="text-accent hover:text-accent-hover no-underline" {...props} />
  ),
  code: ({
    className,
    children,
    ...props
  }: React.HTMLAttributes<HTMLElement> & { children?: React.ReactNode }) => {
    if (className && /language-\w+/.test(className)) {
      const code = String(children ?? "").replace(/\n$/, "");
      const language = extractLanguage(className);
      return (
        <CodeBlock
          className="my-2 text-[11px]"
          code={code}
          language={language}
        >
          <CodeBlockHeader className="px-2.5 py-1 text-[10px]">
            <CodeBlockTitle>
              <CodeBlockFilename className="text-[10px] text-muted-foreground">
                {language}
              </CodeBlockFilename>
            </CodeBlockTitle>
            <CodeBlockCopyButton className="size-6 text-muted-foreground hover:text-foreground" />
          </CodeBlockHeader>
        </CodeBlock>
      );
    }
    return (
      <code
        className="bg-surface-code text-accent text-[11px] font-mono px-1.5 py-0.5 rounded-[4px]"
        {...props}
      >
        {children}
      </code>
    );
  },
  pre: ({ children, ...props }: React.HTMLAttributes<HTMLPreElement>) => {
    const child = Array.isArray(children) ? children[0] : children;
    if (
      child &&
      typeof child === "object" &&
      "props" in child &&
      (child as { props?: { className?: string } }).props?.className?.includes(
        "language-",
      )
    ) {
      return <>{children}</>;
    }
    return (
      <pre
        className="bg-surface-code border border-border-subtle rounded-md p-3 text-[11px] font-mono overflow-x-auto my-2"
        {...props}
      >
        {children}
      </pre>
    );
  },
  table: (props: React.HTMLAttributes<HTMLTableElement>) => (
    <table className="w-full text-[13px] my-2 [&_tr:nth-child(even)]:bg-surface-elevated/40" {...props} />
  ),
  th: (props: React.ThHTMLAttributes<HTMLTableCellElement>) => (
    <th className="text-left font-medium px-2 py-1 border-b border-border-subtle" {...props} />
  ),
  td: (props: React.TdHTMLAttributes<HTMLTableCellElement>) => (
    <td className="px-2 py-1 border-b border-border-subtle" {...props} />
  ),
  p: (props: React.HTMLAttributes<HTMLParagraphElement>) => (
    <p className="my-1.5 leading-relaxed" {...props} />
  ),
  ul: (props: React.HTMLAttributes<HTMLUListElement>) => (
    <ul className="list-disc pl-5 my-1.5 space-y-1" {...props} />
  ),
  ol: (props: React.OlHTMLAttributes<HTMLOListElement>) => (
    <ol className="list-decimal pl-5 my-1.5 space-y-1" {...props} />
  ),
};
