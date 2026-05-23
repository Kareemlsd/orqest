"use client";

/**
 * RecentlyClosedMenu — dropdown listing tabs closed within the last
 * 24 h. Click an entry to restore. When the list is empty (or the
 * window has nothing in it), the trigger renders nothing so the
 * Computer-pane header doesn't carry dead chrome.
 *
 * Open state lives in this component (one boolean) — the parent only
 * supplies the data + the restore action. Click-outside-to-close is
 * handled via a global listener wired to a ref on the panel.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

import type { Tab } from "@/hooks/useTabs";

interface RecentlyClosedMenuProps {
  closed: Tab[];
  onRestore: (id: string) => void;
}

const KIND_GLYPH: Record<Tab["kind"], string> = {
  shell: "❯",
  files: "▢",
  browser: "◎",
  editor: "✎",
  chart_gallery: "▲",
  report: "▤",
  memory: "◇",
  agents: "◐",
  component: "◆",
};

export function RecentlyClosedMenu({ closed, onRestore }: RecentlyClosedMenuProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const handleSelect = useCallback(
    (id: string) => {
      onRestore(id);
      setOpen(false);
    },
    [onRestore],
  );

  useEffect(() => {
    if (!open) return;
    const onDocMouseDown = (e: MouseEvent) => {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocMouseDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocMouseDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (closed.length === 0) return null;

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title={`${closed.length} recently closed (last 24 h)`}
        className={cn(
          "font-mono text-[10px] text-muted-foreground hover:text-foreground transition-colors px-1.5 py-1 rounded-sm hover:bg-surface-elevated",
          open && "bg-surface-elevated text-foreground",
        )}
      >
        ↺ {closed.length}
      </button>
      {open && (
        <div
          role="menu"
          aria-label="Recently closed tabs"
          className="absolute right-0 top-full mt-1 z-40 min-w-[220px] max-w-[320px] rounded-md border border-border-default bg-surface-elevated py-1 shadow-lg"
        >
          <div className="px-3 pt-1.5 pb-1 font-mono text-[10px] uppercase tracking-wide text-muted-foreground/80">
            Recently closed
          </div>
          {closed.slice(0, 12).map((t) => (
            <button
              key={t.id}
              role="menuitem"
              type="button"
              onClick={() => handleSelect(t.id)}
              className="flex w-full items-center gap-2 px-3 py-1.5 font-mono text-[11px] text-foreground hover:bg-surface-card text-left"
            >
              <span
                className="shrink-0 text-[10px] text-muted-foreground/70"
                aria-hidden
              >
                {KIND_GLYPH[t.kind] ?? "·"}
              </span>
              <span className="truncate">{t.title}</span>
              {t.closed_at && (
                <span className="ml-auto pl-2 shrink-0 text-[10px] text-muted-foreground/60">
                  {formatRelative(t.closed_at)}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function formatRelative(iso: string): string {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  const seconds = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}
