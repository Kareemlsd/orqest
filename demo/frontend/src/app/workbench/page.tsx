"use client";

/**
 * Orqest Workbench — the canonical reference UI for Orqest-powered apps.
 *
 * Layout: three-zone shell (sidebar × chat × contextual right panel).
 * The right panel has tabs for every Orqest primitive: Artifact, Tasks,
 * Sources, Memory, Trace, Events. Chat stays the anchor; context swaps.
 */

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Brain,
  Code2,
  Eye,
  FileText,
  Hexagon,
  ListChecks,
  Sparkles,
  Trash2,
  Waves,
  Zap,
} from "lucide-react";
import { DemoShell } from "@/components/demo-shell";
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import {
  Message,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message";
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolInput,
  ToolOutput,
} from "@/components/ai-elements/tool";
import {
  PromptInput,
  PromptInputTextarea,
  PromptInputSubmit,
} from "@/components/ai-elements/prompt-input";
import { CodeBlock } from "@/components/ai-elements/code-block";

// ─── Types ───────────────────────────────────────────────────────────────

type ArtifactKind = "html" | "svg" | "jsx" | "python" | "markdown";

type Artifact = {
  title: string;
  language: ArtifactKind;
  code: string;
  toolCallId: string;
};

type PlanStep = {
  index: number;
  description: string;
  status: "pending" | "running" | "complete" | "error";
  result: string;
};

type Plan = {
  goal: string;
  steps: PlanStep[];
  toolCallId: string;
};

type SourceEntry = {
  index: number;
  title: string;
  url: string;
};

type MemoryEntry = {
  id: string;
  content: string;
  memory_type: string;
  source_agent: string;
  confidence: number;
  metadata: Record<string, unknown>;
  created_at: string;
  reliability_score: number;
  access_count: number;
};

type TraceSpan = {
  name: string;
  agent_name: string;
  duration_ms?: number;
  status: string;
  started_at: string;
};

type BusEvent = {
  event_type: string;
  agent_name: string;
  timestamp: string;
  data: Record<string, unknown>;
};

type SidecarState = {
  memories: MemoryEntry[];
  trace: TraceSpan[];
  events: BusEvent[];
};

type PanelTab =
  | "artifact"
  | "tasks"
  | "sources"
  | "memory"
  | "trace"
  | "events";

// ─── Helpers ─────────────────────────────────────────────────────────────

const TAB_ORDER: {
  id: PanelTab;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}[] = [
  { id: "artifact", label: "Artifact", icon: Sparkles },
  { id: "tasks", label: "Tasks", icon: ListChecks },
  { id: "sources", label: "Sources", icon: FileText },
  { id: "memory", label: "Memory", icon: Brain },
  { id: "trace", label: "Trace", icon: Waves },
  { id: "events", label: "Events", icon: Zap },
];

type AnyPart = {
  type: string;
  toolCallId?: string;
  input?: unknown;
  output?: unknown;
  state?: string;
};

// ─── Component ───────────────────────────────────────────────────────────

export default function Workbench() {
  const [tab, setTab] = useState<PanelTab>("artifact");
  const [sidecar, setSidecar] = useState<SidecarState>({
    memories: [],
    trace: [],
    events: [],
  });

  const { messages, sendMessage, status, error } = useChat({
    transport: new DefaultChatTransport({ api: "/api/workbench/chat" }),
  });

  // ── Extract latest plan / artifact / sources from messages ────────────

  const artifacts = useMemo<Artifact[]>(() => {
    const out: Artifact[] = [];
    for (const m of messages) {
      if (m.role !== "assistant") continue;
      for (const part of m.parts as unknown as AnyPart[]) {
        if (
          part.toolCallId &&
          part.type === "tool-emit_artifact" &&
          part.input &&
          typeof part.input === "object"
        ) {
          const inp = part.input as {
            title?: string;
            language?: string;
            code?: string;
          };
          if (inp.code && inp.language && inp.title) {
            out.push({
              title: inp.title,
              language: inp.language as ArtifactKind,
              code: inp.code,
              toolCallId: part.toolCallId,
            });
          }
        }
      }
    }
    return out;
  }, [messages]);
  const latestArtifact = artifacts[artifacts.length - 1] ?? null;

  const plans = useMemo<Plan[]>(() => {
    const out: Plan[] = [];
    for (const m of messages) {
      if (m.role !== "assistant") continue;
      for (const part of m.parts as unknown as AnyPart[]) {
        if (
          part.toolCallId &&
          part.type === "tool-emit_plan" &&
          part.input &&
          typeof part.input === "object"
        ) {
          const inp = part.input as { goal?: string; steps?: PlanStep[] };
          if (inp.goal && Array.isArray(inp.steps)) {
            out.push({
              goal: inp.goal,
              steps: inp.steps,
              toolCallId: part.toolCallId,
            });
          }
        }
      }
    }
    return out;
  }, [messages]);
  const latestPlan = plans[plans.length - 1] ?? null;

  const sources = useMemo<SourceEntry[]>(() => {
    const seen = new Map<string, SourceEntry>();
    for (const m of messages) {
      if (m.role !== "assistant") continue;
      for (const part of m.parts as unknown as AnyPart[]) {
        // Parse **Sources** section from text parts
        if (part.type === "text") {
          const text = (part as { text?: string }).text ?? "";
          const sourcesMatch = text.match(/\*\*Sources\*\*\s*\n([\s\S]*?)$/);
          if (!sourcesMatch) continue;
          for (const line of sourcesMatch[1].split("\n")) {
            const m2 = line.match(/\[(\d+)\]\s*(.+?)\s*[—–-]\s*(https?:\S+)/);
            if (m2) {
              seen.set(m2[3].trim(), {
                index: parseInt(m2[1], 10),
                title: m2[2].trim(),
                url: m2[3].trim(),
              });
            }
          }
        }
        // Also extract from web_search tool output (JSON array)
        if (
          part.type === "tool-web_search" &&
          part.state === "output-available" &&
          typeof part.output === "string"
        ) {
          try {
            const parsed = JSON.parse(part.output);
            if (Array.isArray(parsed)) {
              for (const s of parsed) {
                if (s.url && s.title) {
                  seen.set(s.url, {
                    index: s.index,
                    title: s.title,
                    url: s.url,
                  });
                }
              }
            }
          } catch {
            // ignore
          }
        }
      }
    }
    return Array.from(seen.values()).sort((a, b) => a.index - b.index);
  }, [messages]);

  // ── Poll sidecar state ────────────────────────────────────────────────

  const fetchSidecar = useCallback(async () => {
    try {
      const res = await fetch("/api/workbench/state");
      if (!res.ok) return;
      const data = (await res.json()) as SidecarState;
      setSidecar(data);
    } catch {
      // silent; demo is best-effort
    }
  }, []);

  useEffect(() => {
    fetchSidecar();
    const intervalMs = status === "streaming" || status === "submitted" ? 1000 : 4000;
    const t = setInterval(fetchSidecar, intervalMs);
    return () => clearInterval(t);
  }, [fetchSidecar, status]);

  // Auto-switch tab when a new artifact / plan / sources appears
  useEffect(() => {
    if (latestArtifact) setTab("artifact");
  }, [latestArtifact?.toolCallId]);
  useEffect(() => {
    if (latestPlan) setTab("tasks");
  }, [latestPlan?.toolCallId]);

  // ── Handlers ──────────────────────────────────────────────────────────

  const handleSubmit = (message: { text?: string }) => {
    const text = message.text?.trim();
    if (!text) return;
    sendMessage({ text });
  };

  const resetSession = async () => {
    await fetch("/api/workbench/reset", { method: "POST" });
    fetchSidecar();
  };

  const forgetMemory = async (id: string) => {
    await fetch("/api/workbench/memory/forget", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    fetchSidecar();
  };

  // Tab badge counts
  const counts: Record<PanelTab, number> = {
    artifact: artifacts.length,
    tasks: plans.length,
    sources: sources.length,
    memory: sidecar.memories.length,
    trace: sidecar.trace.length,
    events: sidecar.events.length,
  };

  const isStreaming = status === "streaming" || status === "submitted";

  return (
    <DemoShell
      title="Workbench"
      subtitle="The canonical Orqest-powered app — chat × artifacts × tasks × memory × trace"
    >
      <div className="flex h-full">
        {/* ─── Chat column ─── */}
        <div className="flex-1 min-w-0 flex flex-col border-r border-border/60">
          <div className="flex-1 overflow-hidden">
            <Conversation className="h-full">
              <ConversationContent className="max-w-3xl mx-auto px-6 py-6">
                {messages.length === 0 && (
                  <ConversationEmptyState
                    title="The Orqest Workbench is ready."
                    description="Try: 'My name is Alex. Plan a weekend in Kyoto, then make an SVG of a torii gate.' · 'What's the state of quantum computing in 2026?' · 'Remember that I prefer dark mode.'"
                  />
                )}

                {messages.map((m) => (
                  <Message key={m.id} from={m.role}>
                    <MessageContent>
                      {m.parts.map((rawPart, i) => {
                        const part = rawPart as unknown as AnyPart & {
                          text?: string;
                        };
                        const key = `${m.id}-${i}`;

                        if (part.type === "text") {
                          // Strip Sources section — it lives in the right panel.
                          const text = (part.text ?? "").replace(
                            /\*\*Sources\*\*\s*\n[\s\S]*$/,
                            ""
                          );
                          if (!text.trim()) return null;
                          return (
                            <MessageResponse key={key}>{text}</MessageResponse>
                          );
                        }

                        if (part.toolCallId) {
                          // Artifact/plan tool calls are rendered as compact stubs —
                          // their full content lives in the right panel.
                          const name = part.type.replace(/^tool-/, "");
                          if (name === "emit_artifact") {
                            const inp = (part.input ?? {}) as {
                              title?: string;
                              language?: string;
                            };
                            return (
                              <InlineStub
                                key={key}
                                icon="sparkles"
                                label="Artifact"
                                value={`${inp.title ?? "(loading)"} · ${inp.language ?? "..."}`}
                                onClick={() => setTab("artifact")}
                              />
                            );
                          }
                          if (name === "emit_plan") {
                            const inp = (part.input ?? {}) as {
                              goal?: string;
                              steps?: unknown[];
                            };
                            return (
                              <InlineStub
                                key={key}
                                icon="tasks"
                                label="Plan"
                                value={`${inp.goal ?? "(loading)"} · ${Array.isArray(inp.steps) ? inp.steps.length : "?"} steps`}
                                onClick={() => setTab("tasks")}
                              />
                            );
                          }
                          if (name === "remember" || name === "recall") {
                            const inp = (part.input ?? {}) as {
                              content?: string;
                              query?: string;
                            };
                            return (
                              <InlineStub
                                key={key}
                                icon="brain"
                                label={name === "remember" ? "Remember" : "Recall"}
                                value={inp.content ?? inp.query ?? "(...)"}
                                onClick={() => setTab("memory")}
                              />
                            );
                          }

                          // Generic tool — show the full Tool card inline.
                          return (
                            <Tool key={key}>
                              <ToolHeader
                                type={part.type as `tool-${string}`}
                                state={
                                  (part.state ?? "input-streaming") as
                                    | "input-streaming"
                                    | "input-available"
                                    | "output-available"
                                    | "output-error"
                                }
                              />
                              <ToolContent>
                                <ToolInput input={part.input} />
                                {(part.state === "output-available" ||
                                  part.state === "output-error") && (
                                  <ToolOutput
                                    output={
                                      typeof part.output === "string"
                                        ? part.output
                                        : JSON.stringify(
                                            part.output ?? null,
                                            null,
                                            2
                                          )
                                    }
                                    errorText={undefined}
                                  />
                                )}
                              </ToolContent>
                            </Tool>
                          );
                        }

                        return null;
                      })}
                    </MessageContent>
                  </Message>
                ))}

                {error && (
                  <div className="rounded-md border border-destructive bg-destructive/10 p-3 text-sm text-destructive">
                    Error: {error.message}
                  </div>
                )}
              </ConversationContent>
              <ConversationScrollButton />
            </Conversation>
          </div>

          {/* Hairline streaming indicator */}
          {isStreaming && (
            <div className="h-[2px] w-full overflow-hidden">
              <div className="h-full bg-teal-500/80 animate-[stream-bar_1.2s_ease-in-out_infinite]" />
            </div>
          )}

          <div className="border-t border-border/60 p-4">
            <div className="max-w-3xl mx-auto">
              <PromptInput onSubmit={handleSubmit}>
                <PromptInputTextarea placeholder="Ask anything — the agent will choose the right tools, panels, and memory for you..." />
                <PromptInputSubmit status={status} />
              </PromptInput>
              <div className="flex items-center justify-between mt-2 text-[10px] text-muted-foreground">
                <p>
                  Tools: get_time · calculate · web_search · remember · recall ·
                  emit_plan · emit_artifact
                </p>
                <button
                  onClick={resetSession}
                  className="hover:text-foreground transition-colors"
                >
                  Clear session
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* ─── Context panel ─── */}
        <aside className="w-[440px] flex flex-col bg-background">
          {/* Tabs */}
          <div className="border-b border-border/60 flex items-center overflow-x-auto">
            {TAB_ORDER.map(({ id, label, icon: Icon }) => {
              const count = counts[id];
              const active = tab === id;
              return (
                <button
                  key={id}
                  onClick={() => setTab(id)}
                  className={`flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium border-b-2 transition-colors whitespace-nowrap ${
                    active
                      ? "border-teal-500 text-foreground"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  <span>{label}</span>
                  {count > 0 && (
                    <span
                      className={`text-[9px] font-mono px-1 py-px rounded ${
                        active
                          ? "bg-teal-500/20 text-teal-400"
                          : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* Panel content */}
          <div className="flex-1 overflow-auto">
            {tab === "artifact" && (
              <ArtifactPanel artifact={latestArtifact} />
            )}
            {tab === "tasks" && <TasksPanel plan={latestPlan} />}
            {tab === "sources" && <SourcesPanel sources={sources} />}
            {tab === "memory" && (
              <MemoryPanel
                entries={sidecar.memories}
                onForget={forgetMemory}
              />
            )}
            {tab === "trace" && <TracePanel spans={sidecar.trace} />}
            {tab === "events" && <EventsPanel events={sidecar.events} />}
          </div>
        </aside>
      </div>

      <style jsx global>{`
        @keyframes stream-bar {
          0% {
            transform: translateX(-100%);
          }
          50% {
            transform: translateX(0);
          }
          100% {
            transform: translateX(100%);
          }
        }
      `}</style>
    </DemoShell>
  );
}

// ─── Sub-components ──────────────────────────────────────────────────────

function InlineStub({
  icon,
  label,
  value,
  onClick,
}: {
  icon: "sparkles" | "tasks" | "brain";
  label: string;
  value: string;
  onClick: () => void;
}) {
  const Icon =
    icon === "sparkles" ? Sparkles : icon === "tasks" ? ListChecks : Brain;
  return (
    <button
      onClick={onClick}
      className="group flex items-center gap-2 my-1.5 w-full text-left rounded-md border border-border/60 bg-card/50 hover:bg-card hover:border-border px-2.5 py-1.5 text-xs transition-colors"
    >
      <Icon className="w-3.5 h-3.5 text-teal-500 flex-shrink-0" />
      <span className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground">
        {label}
      </span>
      <span className="truncate text-foreground">{value}</span>
      <span className="ml-auto text-[10px] text-muted-foreground group-hover:text-foreground">
        View →
      </span>
    </button>
  );
}

function EmptyPanel({
  icon: Icon,
  title,
  description,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center p-8">
      <div className="w-12 h-12 rounded-md border border-border/60 flex items-center justify-center mb-4 text-muted-foreground">
        <Icon className="w-5 h-5" />
      </div>
      <p className="text-sm font-medium">{title}</p>
      <p className="text-xs text-muted-foreground mt-1 max-w-xs">
        {description}
      </p>
    </div>
  );
}

// — Artifact tab —

function ArtifactPanel({ artifact }: { artifact: Artifact | null }) {
  const [view, setView] = useState<"preview" | "code">("preview");

  if (!artifact) {
    return (
      <EmptyPanel
        icon={Sparkles}
        title="No artifact yet"
        description="Ask the agent for an SVG, HTML page, React component, Python script, or markdown."
      />
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="border-b border-border/60 px-3 py-2 flex items-center gap-2">
        <p className="text-xs font-mono text-muted-foreground uppercase">
          {artifact.language}
        </p>
        <p className="text-sm font-medium truncate flex-1">{artifact.title}</p>
        <div className="flex gap-1">
          <button
            onClick={() => setView("preview")}
            className={`flex items-center gap-1 px-2 py-0.5 text-[11px] rounded transition-colors ${
              view === "preview"
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:bg-accent/50"
            }`}
          >
            <Eye className="w-3 h-3" />
            Preview
          </button>
          <button
            onClick={() => setView("code")}
            className={`flex items-center gap-1 px-2 py-0.5 text-[11px] rounded transition-colors ${
              view === "code"
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:bg-accent/50"
            }`}
          >
            <Code2 className="w-3 h-3" />
            Code
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-hidden">
        {view === "preview" ? (
          <ArtifactPreview artifact={artifact} />
        ) : (
          <div className="h-full overflow-auto p-4">
            <CodeBlock
              code={artifact.code}
              language={
                artifact.language === "svg" ? "xml" : artifact.language
              }
            />
          </div>
        )}
      </div>
    </div>
  );
}

function ArtifactPreview({ artifact }: { artifact: Artifact }) {
  if (artifact.language === "svg") {
    return (
      <div
        className="w-full h-full flex items-center justify-center p-8 bg-white overflow-auto"
        dangerouslySetInnerHTML={{ __html: artifact.code }}
      />
    );
  }
  if (artifact.language === "html") {
    return (
      <iframe
        srcDoc={artifact.code}
        className="w-full h-full bg-white"
        sandbox="allow-scripts"
        title="HTML Preview"
      />
    );
  }
  if (artifact.language === "jsx") {
    const html = `<!DOCTYPE html><html><head>
<script src="https://unpkg.com/react@19/umd/react.development.js"></script>
<script src="https://unpkg.com/react-dom@19/umd/react-dom.development.js"></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
<style>body { margin:0; padding:1.25rem; font-family:system-ui,sans-serif; }</style>
</head><body><div id="root"></div>
<script type="text/babel">
${artifact.code}
const __Component = typeof Component !== 'undefined' ? Component :
  typeof App !== 'undefined' ? App :
  typeof Main !== 'undefined' ? Main :
  (() => React.createElement('pre', null, 'Name your component App, Component, or Main.'));
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(__Component));
</script></body></html>`;
    return (
      <iframe
        srcDoc={html}
        className="w-full h-full bg-white"
        sandbox="allow-scripts"
        title="React Preview"
      />
    );
  }
  if (artifact.language === "markdown") {
    return (
      <div className="h-full overflow-auto p-6 prose prose-invert max-w-none text-sm">
        <pre className="whitespace-pre-wrap font-sans">{artifact.code}</pre>
      </div>
    );
  }
  // python
  return (
    <div className="p-6 text-sm text-muted-foreground flex items-center justify-center h-full">
      No visual preview for {artifact.language} — switch to the Code tab.
    </div>
  );
}

// — Tasks tab —

function TasksPanel({ plan }: { plan: Plan | null }) {
  if (!plan) {
    return (
      <EmptyPanel
        icon={ListChecks}
        title="No plan yet"
        description="Give the agent a multi-step goal and a task tree will appear here with live progress."
      />
    );
  }
  const done = plan.steps.filter((s) => s.status === "complete").length;
  return (
    <div className="p-4 space-y-3">
      <div>
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
          Goal
        </p>
        <p className="text-sm font-medium mt-0.5 leading-snug">{plan.goal}</p>
        <p className="text-xs text-muted-foreground mt-1">
          {done} of {plan.steps.length} complete
        </p>
      </div>
      <div className="space-y-2">
        {plan.steps.map((step) => (
          <div
            key={`step-${step.index}`}
            className="rounded-md border border-border/60 bg-card p-3"
          >
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs font-mono text-muted-foreground">
                Step {step.index}
              </p>
              <span
                className={`text-[9px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded ${
                  step.status === "complete"
                    ? "bg-teal-500/10 text-teal-400"
                    : step.status === "running"
                      ? "bg-blue-500/10 text-blue-400"
                      : step.status === "error"
                        ? "bg-red-500/10 text-red-400"
                        : "bg-muted text-muted-foreground"
                }`}
              >
                {step.status}
              </span>
            </div>
            <p className="text-sm mt-1 leading-snug">{step.description}</p>
            {step.result && (
              <p className="text-xs text-muted-foreground mt-1.5 italic border-l-2 border-border/60 pl-2">
                {step.result}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// — Sources tab —

function SourcesPanel({ sources }: { sources: SourceEntry[] }) {
  if (sources.length === 0) {
    return (
      <EmptyPanel
        icon={FileText}
        title="No sources cited"
        description="When the agent searches the web, cited sources accumulate here."
      />
    );
  }
  return (
    <div className="p-4 space-y-2">
      {sources.map((s) => (
        <a
          key={s.url}
          href={s.url}
          target="_blank"
          rel="noopener noreferrer"
          className="group flex items-start gap-3 p-3 rounded-md border border-border/60 bg-card hover:border-border transition-colors"
        >
          <div className="w-6 h-6 rounded bg-muted text-xs font-mono flex items-center justify-center flex-shrink-0 text-muted-foreground group-hover:text-foreground">
            {s.index}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium leading-snug group-hover:underline">
              {s.title}
            </p>
            <p className="text-xs text-muted-foreground mt-1 truncate">
              {(() => {
                try {
                  return new URL(s.url).hostname;
                } catch {
                  return s.url;
                }
              })()}
            </p>
          </div>
        </a>
      ))}
    </div>
  );
}

// — Memory tab —

function MemoryPanel({
  entries,
  onForget,
}: {
  entries: MemoryEntry[];
  onForget: (id: string) => void;
}) {
  if (entries.length === 0) {
    return (
      <EmptyPanel
        icon={Brain}
        title="No memories yet"
        description="Tell the agent about yourself or your preferences. It'll call `remember` and you'll see entries here."
      />
    );
  }
  return (
    <div className="p-4 space-y-2">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-2">
        LocalMemoryStore · SQLite + FTS5
      </p>
      {entries.map((e) => (
        <div
          key={e.id}
          className="group rounded-md border border-border/60 bg-card p-3"
        >
          <div className="flex items-start gap-2">
            <Hexagon className="w-3.5 h-3.5 text-teal-500 flex-shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <p className="text-sm leading-snug">{e.content}</p>
              <div className="flex items-center gap-2 mt-1.5 text-[10px] text-muted-foreground">
                <span className="font-mono">{e.memory_type}</span>
                <span>·</span>
                <span>reliability {e.reliability_score.toFixed(2)}</span>
                <span>·</span>
                <span>accessed {e.access_count}×</span>
              </div>
            </div>
            <button
              onClick={() => onForget(e.id)}
              className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-opacity"
              title="Forget this memory"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

// — Trace tab —

function TracePanel({ spans }: { spans: TraceSpan[] }) {
  if (spans.length === 0) {
    return (
      <EmptyPanel
        icon={Waves}
        title="No traces yet"
        description="Each agent run produces a JSONTracer span. They appear here with duration and status."
      />
    );
  }
  return (
    <div className="p-4 space-y-2">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-2">
        JSONTracer · {spans.length} spans
      </p>
      {spans.map((s, i) => (
        <div
          key={i}
          className="rounded-md border border-border/60 bg-card p-3"
        >
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-mono">{s.name}</p>
            <span
              className={`text-[9px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded ${
                s.status === "ok"
                  ? "bg-teal-500/10 text-teal-400"
                  : "bg-red-500/10 text-red-400"
              }`}
            >
              {s.status}
            </span>
          </div>
          <div className="flex items-center gap-3 mt-1 text-[11px] text-muted-foreground">
            <span>{s.agent_name}</span>
            {typeof s.duration_ms === "number" && (
              <span>{s.duration_ms.toFixed(1)}ms</span>
            )}
            <span className="font-mono">{s.started_at.slice(11, 19)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

// — Events tab —

function EventsPanel({ events }: { events: BusEvent[] }) {
  if (events.length === 0) {
    return (
      <EmptyPanel
        icon={Activity}
        title="No events yet"
        description="Tool calls, memory writes, and artifact emissions fire events on the EventBus. They stream here."
      />
    );
  }
  // Newest last? Newest first is more useful
  const reversed = [...events].reverse();
  return (
    <div className="p-4 space-y-1">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-2">
        EventBus · {events.length} events
      </p>
      {reversed.map((e, i) => (
        <div
          key={`${e.event_type}-${e.timestamp}-${i}`}
          className="flex items-start gap-2 rounded-md border border-border/60 bg-card/60 p-2.5 text-xs"
        >
          <Zap className="w-3 h-3 text-teal-500 flex-shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <p className="font-mono font-medium">{e.event_type}</p>
              <p className="text-[10px] text-muted-foreground">
                {e.timestamp.slice(11, 19)}
              </p>
            </div>
            <pre className="text-[10px] text-muted-foreground mt-0.5 whitespace-pre-wrap break-all">
              {JSON.stringify(e.data, null, 0).slice(0, 200)}
            </pre>
          </div>
        </div>
      ))}
    </div>
  );
}
