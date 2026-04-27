"use client";

/**
 * Two-pane session shell. Left: 560px fixed ChatPane. Right: fluid
 * ComputerPane. Hairline separator between them (ref 6 — Linear's
 * structural-edge-only policy).
 *
 * Top bar: 40px-tall editorial chrome. Diamond-glyph + serif wordmark
 * on the left; mono session id (sliced into a friendlier shape) plus
 * an optional context label derived from the live plan; on the right,
 * model label, the existing token-usage ring (`SessionContext`), and
 * the connection dot rendered as `live`/`idle` per the design brief.
 */
import { use, useMemo, useState } from "react";

import { ChatPane } from "@/components/chat/ChatPane";
import { SessionContext } from "@/components/chat/SessionContext";
import { ComputerPane } from "@/components/computer/ComputerPane";
import { TakeoverDialogModal } from "@/components/computer/TakeoverDialogModal";
import { HealingToasts } from "@/components/healing/HealingToasts";
import { TooltipProvider } from "@/components/ui/tooltip";
import { SidecarProvider } from "@/hooks/SidecarProvider";
import { UIComponentsProvider } from "@/hooks/UIComponentsProvider";
import { usePlan } from "@/hooks/usePlan";
import { useSidecar } from "@/hooks/useSidecar";
import { cn } from "@/lib/utils";

interface SessionPageProps {
  params: Promise<{ id: string }>;
}

export default function SessionPage({ params }: SessionPageProps) {
  const { id } = use(params);

  // Single shared EventSource for the whole session subtree. All hooks
  // (`usePlan`, `useArtifacts`, `useTakeover`, `useUIComponents`, plus
  // every `useSidecar` consumer in the Computer pane) subscribe through
  // this provider instead of opening their own SSE connections.
  // `TooltipProvider` mounts at the root of the session subtree so any
  // descendant that uses Radix `Tooltip` (AI Elements `Checkpoint`,
  // `Actions`, `TakeoverButton`, future hovers) just works without
  // each component needing to wrap its own provider. Single
  // `delayDuration` keeps tooltip timing consistent across the surface.
  return (
    <TooltipProvider delayDuration={200}>
      <SidecarProvider sessionId={id}>
        <UIComponentsProvider sessionId={id}>
          <SessionShell id={id} />
        </UIComponentsProvider>
      </SidecarProvider>
    </TooltipProvider>
  );
}

/** Slice the long session uuid into a friendlier `XXX-XXXXXX` shape:
 *  three chars, hyphen, six chars, all upper-case mono. Falls back to
 *  whatever's available when the id is shorter than nine characters. */
function formatSessionLabel(id: string): string {
  const slug = id.slice(0, 9).replace(/[^a-zA-Z0-9]/g, "").toUpperCase();
  if (slug.length <= 3) return slug;
  return `${slug.slice(0, 3)}-${slug.slice(3, 9)}`;
}

function SessionShell({ id }: { id: string }) {
  const [connected, setConnected] = useState(false);
  const { plan } = usePlan(id);

  useSidecar(id, () => {
    // Any event (including heartbeat) indicates a live connection.
    if (!connected) setConnected(true);
  });

  const sessionLabel = useMemo(() => formatSessionLabel(id), [id]);
  const context = useMemo(() => {
    // Derive a short editorial context label from the active plan.
    // Prefer the in-progress task's title; fall back to the first task;
    // finally, "idle" when the plan is empty.
    if (!plan.tasks || plan.tasks.length === 0) return "idle";
    const active = plan.tasks.find((t) => t.status === "in-progress")
      ?? plan.tasks[0];
    const title = active.title?.trim();
    if (!title) return "idle";
    // Keep it short — the top bar is dense.
    return title.length > 40 ? `${title.slice(0, 37)}…` : title;
  }, [plan.tasks]);

  return (
    <div className="flex flex-col h-screen w-screen bg-background text-foreground overflow-hidden">
      <header
        className="flex items-center gap-3.5 border-b border-border-subtle px-3.5 shrink-0 bg-background"
        style={{ height: 40 }}
      >
        {/* Diamond glyph + serif wordmark */}
        <div className="flex items-center gap-2.5">
          <div
            className="grid place-items-center relative"
            style={{
              width: 18,
              height: 18,
              borderRadius: 3,
              border: "1px solid var(--color-border-strong)",
            }}
            aria-hidden
          >
            <div
              className="absolute"
              style={{
                inset: 3,
                background: "var(--color-accent)",
                clipPath: "polygon(50% 0,100% 50%,50% 100%,0 50%)",
              }}
            />
          </div>
          <span
            className="font-serif text-foreground"
            style={{ fontSize: 15, fontWeight: 500, letterSpacing: "-0.01em" }}
          >
            Polymath
          </span>
        </div>

        {/* Vertical hairline */}
        <div
          aria-hidden
          style={{
            width: 1,
            height: 16,
            background: "var(--color-border-subtle)",
          }}
        />

        {/* Session id mono ALL-CAPS */}
        <span className="font-mono text-[10px] uppercase tracking-[0.04em] text-muted-foreground">
          {sessionLabel}
        </span>

        {/* Optional context derived from the live plan title */}
        <span className="font-mono text-[10px] uppercase tracking-[0.04em] text-muted-foreground/80 -ml-1 truncate">
          · {context} · turn {String(plan.tasks.length).padStart(2, "0")}
        </span>

        <div className="flex-1" />

        {/* Right side: model · token ring · live indicator */}
        <span className="font-mono text-[10px] uppercase tracking-[0.04em] text-muted-foreground">
          model · opus 4.1
        </span>
        <SessionContext sessionId={id} />
        <div className="flex items-center gap-1.5">
          <span
            className={cn(
              "inline-block h-1.5 w-1.5 rounded-full",
              connected ? "bg-accent" : "bg-muted-foreground/40",
            )}
            style={
              connected
                ? {
                    boxShadow: "0 0 0 2px var(--color-accent-subtle)",
                  }
                : undefined
            }
            aria-hidden
          />
          <span className="font-mono text-[10px] uppercase tracking-[0.04em] text-muted-foreground">
            {connected ? "live" : "idle"}
          </span>
        </div>
      </header>
      <main className="flex flex-1 overflow-hidden">
        <aside className="w-[560px] shrink-0 border-r border-border-subtle">
          <ChatPane sessionId={id} />
        </aside>
        <section className="flex-1 min-w-0">
          <ComputerPane sessionId={id} />
        </section>
      </main>
      <TakeoverDialogModal sessionId={id} />
      <HealingToasts sessionId={id} />
    </div>
  );
}
