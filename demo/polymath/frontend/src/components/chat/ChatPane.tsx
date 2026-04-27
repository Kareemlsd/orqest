"use client";

/**
 * ChatPane — left pane. Adapted from numatics-ai ChatV3Panel with FEA
 * specifics removed: no QualityReportCard, no GeoDiffView, no Investigation,
 * no MeshArtifact. Tool rendering is fully pluggable via the `toolRenderers`
 * registry prop (empty in Phase 0).
 *
 * Empty state: editorial masthead — date-stamped session header, a
 * serif display headline ("What should we / think through today?"), a
 * "continuing memory" section listing the three most-recent threads
 * the agent has been holding, and a `commands` legend above the
 * composer. Replaces the prior "Ask Polymath to do anything." +
 * suggestion-chip layout.
 */
import { useCallback, useMemo } from "react";
import { ArrowRight } from "lucide-react";

import { useChat } from "@/hooks/useChat";
import { useChatMetrics } from "@/hooks/useChatMetrics";
import { useMetacognition } from "@/hooks/useMetacognition";
import { usePlan } from "@/hooks/usePlan";
import { useRecentMemory, type RecentMemoryEntry } from "@/hooks/useRecentMemory";

import { Conversation, ConversationContent } from "@/components/ai-elements/conversation";
import { CheckpointDivider } from "./CheckpointDivider";
import { ChatMessage } from "./Message";
import { Composer } from "./Composer";
import { PlanHeader } from "./PlanHeader";
import type { ToolRenderer } from "./ToolCard";

interface ChatPaneProps {
  sessionId: string;
  toolRenderers?: Record<string, ToolRenderer>;
}

/**
 * Frozen module-level fallback so the default `toolRenderers ?? {}`
 * doesn't mint a fresh object on every `ChatPane` render — that would
 * defeat `React.memo` on `<ChatMessage>` because every historical
 * message would see a "new" prop reference and re-render whenever a
 * streaming token lands.
 */
const EMPTY_RENDERERS: Record<string, ToolRenderer> = Object.freeze({});

export function ChatPane({ sessionId, toolRenderers }: ChatPaneProps) {
  const { messages, status, sendMessage, stop } = useChat({ sessionId });
  const { plan } = usePlan(sessionId);

  // Surface the cognitive backbone — bind the metacognition hook to
  // the in-flight assistant message id so per-message confidence can
  // be frozen when the stream closes.
  const currentAssistantId = useMemo<string | null>(() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant") return messages[i].id;
    }
    return null;
  }, [messages]);
  const metacognition = useMetacognition(
    sessionId,
    currentAssistantId,
    status,
  );
  const chatMetrics = useChatMetrics(sessionId, currentAssistantId);

  // Stabilise the renderers prop. Without this every render would create
  // a new `{}` (or wrap the prop), busting `React.memo` on every
  // historical `ChatMessage` whenever the streaming assistant message
  // ticks.
  const renderers = useMemo(
    () => toolRenderers ?? EMPTY_RENDERERS,
    [toolRenderers],
  );

  // Regenerate handler: walk back from the assistant message to find
  // the immediately-preceding user prompt and re-`sendMessage` it.
  const handleRegenerate = useCallback(
    (assistantMessageId: string) => {
      const idx = messages.findIndex((m) => m.id === assistantMessageId);
      if (idx <= 0) return;
      for (let i = idx - 1; i >= 0; i--) {
        const m = messages[i];
        if (m.role !== "user") continue;
        const text = (m.parts ?? [])
          .map((p) => {
            if (
              typeof p === "object" &&
              p !== null &&
              (p as { type?: string }).type === "text"
            ) {
              const t = (p as { text?: unknown }).text;
              return typeof t === "string" ? t : "";
            }
            return "";
          })
          .filter((s) => s.length > 0)
          .join("\n\n");
        if (!text) return;
        sendMessage({ text });
        return;
      }
    },
    [messages, sendMessage],
  );

  const empty = messages.length === 0 && status !== "streaming" && status !== "submitted";
  const isStreamingNow = status === "streaming" || status === "submitted";

  return (
    <div className="flex flex-col h-full bg-background">
      <PlanHeader plan={plan} />
      <Conversation className="flex-1 overflow-y-auto">
        <ConversationContent className="gap-4 px-4 py-4">
          {empty ? (
            <EmptyState sessionId={sessionId} turnCount={messages.length} />
          ) : (
            messages.map((m, idx) => {
              const isLatest = m.id === currentAssistantId;
              return (
                <div key={m.id}>
                  <ChatMessage
                    sessionId={sessionId}
                    message={m}
                    turnIndex={idx + 1}
                    toolRenderers={renderers}
                    metacognition={metacognition.getMetaForMessage(m.id)}
                    metrics={chatMetrics.getMetricsForMessage(m.id)}
                    isStreaming={isLatest && isStreamingNow}
                    onRegenerate={handleRegenerate}
                  />
                  <CheckpointDivider
                    afterMessageId={m.id}
                    latestAssistantMessageId={currentAssistantId}
                    sessionId={sessionId}
                  />
                </div>
              );
            })
          )}
        </ConversationContent>
      </Conversation>
      <Composer
        status={status}
        onSend={(text) => sendMessage({ text })}
        onStop={stop}
      />
    </div>
  );
}

interface EmptyStateProps {
  sessionId: string;
  turnCount: number;
}

/**
 * Editorial empty state. Mirrors `pm-screens.jsx:32-127` — masthead
 * row, serif display headline with `think through` italicised in
 * accent, "continuing memory" section feeding off `useRecentMemory`,
 * and a `commands` legend pinned above the composer.
 */
function EmptyState({ sessionId, turnCount }: EmptyStateProps) {
  const { entries, isEmpty } = useRecentMemory(sessionId, 3);
  const sessionLabel = useMemo(() => formatSessionLabel(sessionId), [sessionId]);
  const dateLabel = useMemo(() => formatToday(), []);

  return (
    <div className="flex flex-col px-9 pt-10 pb-3 gap-0">
      {/* Masthead */}
      <div className="flex items-center gap-2.5">
        <span
          className="font-mono text-[10px] uppercase tracking-wide"
          style={{ color: "var(--color-muted-foreground)" }}
        >
          session {sessionLabel} · {dateLabel}
        </span>
        <div
          className="flex-1 h-px"
          style={{ background: "var(--color-border-subtle)" }}
        />
        <span
          className="font-mono text-[10px] uppercase tracking-wide"
          style={{ color: "var(--color-muted-foreground)" }}
        >
          {turnCount === 0
            ? "cold start · 0 turns"
            : `warm · ${turnCount} turn${turnCount === 1 ? "" : "s"}`}
        </span>
      </div>

      {/* Headline */}
      <h1
        className="font-serif font-normal text-[44px] leading-[1.05] tracking-tight m-0 mt-6 mb-1.5 text-foreground"
      >
        What should we
        <br />
        <em
          className="not-italic font-serif italic"
          style={{ color: "var(--color-accent)" }}
        >
          think through
        </em>{" "}
        today?
      </h1>

      <p
        className="font-serif text-[13.5px] leading-relaxed max-w-[380px] mt-3.5"
        style={{ color: "var(--color-muted-foreground)" }}
      >
        I keep notes between sessions.{" "}
        <span style={{ color: "var(--color-muted-foreground)", opacity: 0.75 }}>
          Below: three threads I've been holding for you.
        </span>
      </p>

      {/* Continuing memory */}
      {!isEmpty && (
        <div className="mt-8 flex flex-col">
          <span
            className="font-mono text-[10px] font-semibold uppercase tracking-wide"
            style={{ color: "var(--color-muted-foreground)" }}
          >
            continuing memory
          </span>
          <div
            className="mt-3 flex flex-col"
            style={{ borderTop: "1px solid var(--color-border-subtle)" }}
          >
            {entries.map((entry, i) => (
              <RememberedThread
                key={entry.id}
                num={String(i + 1).padStart(2, "0")}
                entry={entry}
              />
            ))}
          </div>
        </div>
      )}

      {/* Commands */}
      <div className="mt-8">
        <div
          className="flex items-center gap-2.5"
          style={{ color: "var(--color-muted-foreground)" }}
        >
          <span className="font-mono text-[10px] uppercase tracking-wide">
            commands
          </span>
          <div
            className="flex-1 h-px"
            style={{ background: "var(--color-border-subtle)" }}
          />
        </div>
        <div
          className="mt-2.5 grid grid-cols-2 gap-1.5 font-mono text-[11px]"
          style={{ color: "var(--color-muted-foreground)" }}
        >
          {COMMANDS.map((c) => (
            <div key={c.cmd}>
              {c.cmd}{" "}
              <span style={{ color: "var(--color-muted-foreground)", opacity: 0.6 }}>
                — {c.desc}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const COMMANDS: ReadonlyArray<{ cmd: string; desc: string }> = [
  { cmd: "/plan", desc: "draft a multi-step plan" },
  { cmd: "/recall", desc: "search memory" },
  { cmd: "/branch", desc: "fork from a turn" },
  { cmd: "/spawn", desc: "delegate to a sub-agent" },
];

interface RememberedThreadProps {
  num: string;
  entry: RecentMemoryEntry;
}

function RememberedThread({ num, entry }: RememberedThreadProps) {
  const when = useMemo(() => formatRelative(entry.created_at), [entry.created_at]);
  const kind = entry.kind;
  const pillStyle = pillStyleForKind(kind);

  return (
    <div
      className="py-3.5 flex items-start gap-3.5 cursor-pointer group/thread"
      style={{ borderBottom: "1px solid var(--color-border-subtle)" }}
    >
      <span
        className="font-mono text-[10px] uppercase tracking-wide pt-0.5"
        style={{ color: "var(--color-muted-foreground)", opacity: 0.6 }}
      >
        {num}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2">
          <span className="text-[13.5px] text-foreground truncate">
            {summariseTopic(entry.content)}
          </span>
          {when && (
            <span
              className="font-mono text-[10px] uppercase tracking-wide flex-shrink-0"
              style={{ color: "var(--color-muted-foreground)", opacity: 0.6 }}
            >
              · {when}
            </span>
          )}
        </div>
        <div
          className="text-[12px] mt-1 font-serif italic"
          style={{ color: "var(--color-muted-foreground)" }}
        >
          {entry.source_agent
            ? `from ${entry.source_agent}`
            : kindLabel(kind)}
        </div>
      </div>
      <span
        className="inline-flex items-center px-1.5 py-px rounded-sm font-mono text-[10px] uppercase tracking-wide"
        style={pillStyle}
      >
        {kind}
      </span>
      <span
        className="opacity-60 mt-0.5"
        style={{ color: "var(--color-muted-foreground)" }}
      >
        <ArrowRight className="size-3.5" />
      </span>
    </div>
  );
}

function pillStyleForKind(kind: string): React.CSSProperties {
  switch (kind) {
    case "episodic":
      return {
        color: "var(--color-kind-episodic)",
        border: "1px solid oklch(0.72 0.10 290 / 0.35)",
      };
    case "semantic":
      return {
        color: "var(--color-kind-semantic)",
        border: "1px solid oklch(0.78 0.06 220 / 0.35)",
      };
    case "procedural":
      return {
        color: "var(--color-kind-procedural)",
        border: "1px solid oklch(0.78 0.10 150 / 0.35)",
      };
    default:
      return {
        color: "var(--color-muted-foreground)",
        border: "1px solid var(--color-border-default)",
      };
  }
}

function kindLabel(kind: string): string {
  switch (kind) {
    case "episodic":
      return "episode · captured between sessions";
    case "semantic":
      return "fact · cross-session knowledge";
    case "procedural":
      return "skill · learned routine";
    default:
      return "remembered";
  }
}

/**
 * Trim memory `content` down to a single-line topic. Memory entries
 * can be paragraphs; the empty state surfaces only the first line.
 */
function summariseTopic(content: string): string {
  const trimmed = content.trim();
  if (!trimmed) return "untitled thread";
  const firstLine = trimmed.split(/\n+/, 1)[0].trim();
  if (firstLine.length <= 80) return firstLine;
  return `${firstLine.slice(0, 77).trimEnd()}…`;
}

/**
 * Render a session id as a short editorial label — strip leading
 * `session-` prefix if present, slice to first 4 chars uppercased.
 */
function formatSessionLabel(sessionId: string): string {
  const cleaned = sessionId.replace(/^session-/i, "");
  return cleaned.slice(0, 4).toUpperCase() || "NEW";
}

/**
 * Today as `sun apr 26` — lowercase, three-letter weekday/month.
 */
function formatToday(): string {
  const d = new Date();
  const wd = d.toLocaleDateString("en-US", { weekday: "short" }).toLowerCase();
  const mo = d.toLocaleDateString("en-US", { month: "short" }).toLowerCase();
  const day = d.getDate();
  return `${wd} ${mo} ${day}`;
}

/**
 * Loose relative-time formatter. Returns `null` when the timestamp
 * isn't usable so the caller can omit the trailing `· …` clause.
 */
function formatRelative(iso: string | null): string | null {
  if (!iso) return null;
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return null;
  const seconds = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} days ago`;
  const weeks = Math.floor(days / 7);
  if (weeks < 5) return `${weeks} week${weeks === 1 ? "" : "s"} ago`;
  return new Date(ts).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}
