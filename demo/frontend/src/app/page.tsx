import Link from "next/link";
import {
  MessageSquare,
  PenSquare,
  ListChecks,
  ImageIcon,
  BookOpen,
  ArrowRight,
  Sparkles,
} from "lucide-react";

const DEMOS = [
  {
    href: "/demos/chat",
    icon: MessageSquare,
    title: "Streaming Chat",
    subtitle: "Foundation",
    description:
      "A research assistant that streams text and visualizes tool calls in real time. The baseline for any Orqest agent UI.",
    primitive: "BaseAgent + Tools",
    tags: ["streaming", "tool calls", "useChat"],
  },
  {
    href: "/demos/artifact",
    icon: PenSquare,
    title: "Artifact Studio",
    subtitle: "Claude-style",
    description:
      "Ask for an SVG, HTML page, or React component — watch the code generate on the left and render live on the right.",
    primitive: "Structured Output",
    tags: ["code", "SVG", "live preview"],
  },
  {
    href: "/demos/tasks",
    icon: ListChecks,
    title: "Task Planner",
    subtitle: "Manus-style",
    description:
      "Give the agent a multi-step goal and watch it decompose and execute each step with live progress.",
    primitive: "Structured Output",
    tags: ["decomposition", "planning", "streaming"],
  },
  {
    href: "/demos/multimodal",
    icon: ImageIcon,
    title: "Multimodal Analyst",
    subtitle: "Vision",
    description:
      "Upload a photo or diagram — the agent describes it, extracts objects, and suggests follow-up actions.",
    primitive: "Multimodal Input",
    tags: ["images", "attachments", "vision"],
  },
  {
    href: "/demos/research",
    icon: BookOpen,
    title: "Research Assistant",
    subtitle: "Perplexity-style",
    description:
      "Ask a question — the agent searches, cites sources inline, and keeps a running sources panel.",
    primitive: "Tool Use",
    tags: ["search", "citations"],
  },
];

export default function Home() {
  return (
    <main className="min-h-screen bg-background text-foreground">
      {/* Hero */}
      <div className="border-b border-border/60">
        <div className="max-w-6xl mx-auto px-6 py-16">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 rounded bg-teal-700 flex items-center justify-center text-lg font-bold text-white">
              O
            </div>
            <div>
              <p className="text-xs uppercase tracking-wider text-muted-foreground">
                Agentic framework
              </p>
              <h1 className="text-xl font-semibold tracking-tight">Orqest Demos</h1>
            </div>
          </div>

          <h2 className="text-4xl font-semibold tracking-tight max-w-3xl leading-tight">
            The canonical Orqest UI,{" "}
            <span className="text-muted-foreground">
              plus five focused demos.
            </span>
          </h2>
          <p className="mt-4 max-w-2xl text-muted-foreground leading-relaxed">
            Start in the Workbench — the reference application that demonstrates
            every Orqest primitive in one place. The focused demos below each
            isolate a single UI pattern for study.
          </p>
        </div>
      </div>

      {/* Workbench hero card */}
      <div className="max-w-6xl mx-auto px-6 pt-10">
        <Link
          href="/workbench"
          className="group relative flex flex-col sm:flex-row gap-6 p-8 rounded-xl border border-teal-700/40 bg-gradient-to-br from-teal-950/40 via-card to-card hover:border-teal-600/60 transition-colors overflow-hidden"
        >
          <div className="absolute top-4 right-4 text-[10px] uppercase tracking-[0.2em] text-teal-400 font-semibold">
            Reference
          </div>
          <div className="flex items-center justify-center w-16 h-16 rounded-lg bg-teal-700 text-white flex-shrink-0">
            <Sparkles className="w-7 h-7" />
          </div>
          <div className="flex-1">
            <p className="text-[11px] uppercase tracking-wider text-teal-400 font-semibold">
              The canonical Orqest app
            </p>
            <h3 className="text-2xl font-semibold tracking-tight mt-1">
              Workbench
            </h3>
            <p className="mt-2 text-muted-foreground leading-relaxed max-w-2xl">
              One chat with a rich toolbelt. One right-side panel with tabs for
              every Orqest primitive: artifacts, task plans, citations, memory,
              execution traces, and the event bus. Copy this pattern — don't
              rewrite it.
            </p>
            <div className="mt-4 flex flex-wrap gap-1.5">
              {[
                "LocalMemoryStore",
                "JSONTracer",
                "EventBus",
                "Tool orchestration",
                "Structured output",
              ].map((t) => (
                <span
                  key={t}
                  className="text-[10px] px-2 py-0.5 rounded bg-teal-950/60 text-teal-300 font-mono border border-teal-900/50"
                >
                  {t}
                </span>
              ))}
            </div>
          </div>
          <div className="self-center text-muted-foreground group-hover:text-foreground group-hover:translate-x-1 transition-all">
            <ArrowRight className="w-5 h-5" />
          </div>
        </Link>
      </div>

      {/* Demo grid */}
      <div className="max-w-6xl mx-auto px-6 py-12">
        <p className="text-xs uppercase tracking-wider text-muted-foreground font-semibold mb-4">
          Focused demos · One primitive each
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {DEMOS.map((demo) => {
            const Icon = demo.icon;
            return (
              <Link
                key={demo.href}
                href={demo.href}
                className={`group relative flex flex-col p-6 rounded-lg border border-border/60 hover:border-border bg-card transition-colors ${
                  demo.featured ? "ring-1 ring-teal-700/30" : ""
                }`}
              >
                {demo.featured && (
                  <div className="absolute top-3 right-3 text-[10px] uppercase tracking-wider text-teal-500 font-semibold">
                    Featured
                  </div>
                )}

                <div className="flex items-start gap-3 mb-4">
                  <div className="w-9 h-9 rounded bg-muted flex items-center justify-center text-muted-foreground group-hover:text-foreground transition-colors">
                    <Icon className="w-4 h-4" />
                  </div>
                  <div>
                    <p className="text-[11px] uppercase tracking-wider text-muted-foreground">
                      {demo.subtitle}
                    </p>
                    <h3 className="text-base font-semibold tracking-tight">
                      {demo.title}
                    </h3>
                  </div>
                </div>

                <p className="text-sm text-muted-foreground leading-relaxed mb-4 flex-1">
                  {demo.description}
                </p>

                <div className="flex items-center justify-between">
                  <div className="flex flex-wrap gap-1.5">
                    {demo.tags.slice(0, 2).map((tag) => (
                      <span
                        key={tag}
                        className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground font-mono"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                  <ArrowRight className="w-3.5 h-3.5 text-muted-foreground group-hover:text-foreground group-hover:translate-x-0.5 transition-all" />
                </div>

                <div className="mt-3 pt-3 border-t border-border/40 text-[11px] text-muted-foreground font-mono">
                  {demo.primitive}
                </div>
              </Link>
            );
          })}
        </div>
      </div>

      {/* Footer */}
      <footer className="border-t border-border/60 mt-auto">
        <div className="max-w-6xl mx-auto px-6 py-6 flex items-center justify-between text-xs text-muted-foreground">
          <p>
            Built with{" "}
            <span className="font-mono">pydantic-ai</span> +{" "}
            <span className="font-mono">@ai-sdk/react</span> +{" "}
            <span className="font-mono">ai-elements</span>
          </p>
          <p>Orqest v0.1.0</p>
        </div>
      </footer>
    </main>
  );
}
