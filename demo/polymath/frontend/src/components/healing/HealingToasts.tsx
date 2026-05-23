"use client";

/**
 * HealingToasts — bottom-left transient stack surfacing the agent's
 * self-repair signals (`healing.*` events).
 *
 * Mounts at the session root so it's visible regardless of which tab is
 * active. Each toast carries a mono header (`stall · 23s` / `loop · ×4`
 * / `fallback · openai → anthropic`), a muted detail line, and a
 * left-border severity tint (warning for severity ≥ 0.7, accent for
 * 0.3–0.7, muted for everything below). Auto-dismisses after 8 s; the
 * × button dismisses immediately.
 *
 * Different corner from {@link UndoCloseToast} (bottom-right) so the
 * two surfaces don't collide visually when both fire at once.
 *
 * Anti-AI-slop discipline: no animated spinners, no emoji, no bouncy
 * springs. The toast appears, the user reads it, it goes away.
 */
import { useEffect } from "react";

import { cn } from "@/lib/utils";

import { useHealingEvents, type HealingEntry } from "@/hooks/useHealingEvents";

const AUTO_DISMISS_MS = 8_000;
const MAX_VISIBLE = 4;

interface HealingToastsProps {
  sessionId: string;
}

export function HealingToasts({ sessionId }: HealingToastsProps) {
  const { recent, dismiss } = useHealingEvents(sessionId);
  const visible = recent.slice(0, MAX_VISIBLE);

  if (visible.length === 0) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed bottom-4 left-4 z-50 flex flex-col-reverse gap-2 max-w-[360px]"
    >
      {visible.map((entry) => (
        <Toast key={entry.id} entry={entry} onDismiss={dismiss} />
      ))}
    </div>
  );
}

interface ToastProps {
  entry: HealingEntry;
  onDismiss: (id: string) => void;
}

function Toast({ entry, onDismiss }: ToastProps) {
  useEffect(() => {
    const t = setTimeout(() => onDismiss(entry.id), AUTO_DISMISS_MS);
    return () => clearTimeout(t);
  }, [entry.id, onDismiss]);

  const tint =
    entry.severity >= 0.7
      ? "border-l-warning"
      : entry.severity >= 0.3
        ? "border-l-accent"
        : "border-l-muted-foreground/40";

  return (
    <div
      className={cn(
        "flex items-start gap-2 rounded-md border border-border-default bg-surface-elevated",
        "px-3 py-2 shadow-lg",
        "border-l-2",
        tint,
      )}
    >
      <div className="flex-1 min-w-0">
        <div className="font-mono text-[11px] text-foreground truncate">
          {entry.header}
        </div>
        {entry.detail && (
          <div className="font-mono text-[10px] text-muted-foreground truncate">
            {entry.detail}
          </div>
        )}
      </div>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={() => onDismiss(entry.id)}
        className="shrink-0 mt-0.5 text-muted-foreground/60 hover:text-foreground"
      >
        <svg
          viewBox="0 0 12 12"
          width="9"
          height="9"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        >
          <path d="M3 3 L9 9 M9 3 L3 9" />
        </svg>
      </button>
    </div>
  );
}
