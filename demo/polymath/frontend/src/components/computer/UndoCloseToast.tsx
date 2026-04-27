"use client";

/**
 * UndoCloseToast — bottom-right transient toast offering to restore the
 * most recently closed tab. Auto-dismisses after 5 s; clicking "Undo"
 * calls `onRestore` and dismisses immediately. Driven by `useTabs`'
 * `lastClosed` value — when it flips from null → a Tab, the toast
 * appears for 5 s; the parent calls `ackLastClose` (or the user clicks
 * Undo) to clear the state.
 *
 * Renders nothing when `tab` is null, so the parent can mount the
 * component unconditionally and let it manage its own visibility.
 */
import { useEffect } from "react";

import type { Tab } from "@/hooks/useTabs";

interface UndoCloseToastProps {
  tab: Tab | null;
  onRestore: () => void;
  onDismiss: () => void;
  /** ms before auto-dismiss. Defaults to 5_000. */
  durationMs?: number;
}

export function UndoCloseToast({
  tab,
  onRestore,
  onDismiss,
  durationMs = 5_000,
}: UndoCloseToastProps) {
  useEffect(() => {
    if (!tab) return;
    const t = setTimeout(onDismiss, durationMs);
    return () => clearTimeout(t);
  }, [tab, onDismiss, durationMs]);

  if (!tab) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed bottom-4 right-4 z-50 flex items-center gap-3 rounded-md border border-border-default bg-surface-elevated px-3 py-2 shadow-lg"
    >
      <span className="font-mono text-[11px] text-foreground">
        Closed <span className="text-muted-foreground">·</span>{" "}
        <span className="text-muted-foreground">{tab.title}</span>
      </span>
      <button
        type="button"
        onClick={onRestore}
        className="font-mono text-[11px] text-accent hover:text-accent-hover transition-colors"
      >
        Undo
      </button>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={onDismiss}
        className="text-muted-foreground/60 hover:text-foreground"
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
