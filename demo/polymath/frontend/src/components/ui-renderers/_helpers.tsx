"use client";

/**
 * Shared helpers for Layer 2/3 renderers — small visual primitives used to
 * keep error / loading states tone-consistent across declarative-grammar and
 * sandboxed renderers.
 *
 * Tailwind tokens (defined in `src/app/globals.css`):
 *   - destructive          : error tint (auto light/dark variants)
 *   - muted-foreground     : caption / hint color
 *   - surface-elevated     : panel-on-panel background (skeleton bg)
 *
 * Kept intentionally minimal — these aren't general-purpose toast/spinner
 * widgets, just lowest-friction stand-ins that the declarative renderers
 * (Vega, Mermaid, LaTeX, JSON) use when their underlying lib is loading or
 * has surfaced a parse error.
 */
import type { ReactNode } from "react";

export interface ErrorBoxProps {
  message: ReactNode;
}

export function ErrorBox({ message }: ErrorBoxProps): ReactNode {
  return (
    <div className="border border-destructive/40 bg-destructive/10 text-destructive text-[11px] font-mono px-2 py-1 rounded-md">
      {message}
    </div>
  );
}

export interface SkeletonProps {
  /** Override the default h-32. Pass any Tailwind height class. */
  heightClass?: string;
}

export function Skeleton({ heightClass = "h-32" }: SkeletonProps = {}): ReactNode {
  return (
    <div
      className={`animate-pulse bg-surface-elevated ${heightClass} rounded-md`}
      aria-busy="true"
      aria-label="Loading"
    />
  );
}
