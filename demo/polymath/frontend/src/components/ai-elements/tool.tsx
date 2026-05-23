"use client";

/**
 * Tool primitive — minimal. Phase 0 renders a single card; full
 * collapsibility + status header lives in components/chat/ToolCard.tsx.
 * Kept as a dedicated file for future parity with ai-elements.
 */
import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export const ToolRoot = ({ className, ...props }: HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn("not-prose w-full rounded-md border border-border-default bg-surface-card", className)}
    {...props}
  />
);

export const ToolHeader = ({ className, ...props }: HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn("flex items-center justify-between gap-2 px-3 py-2 text-[11px] font-mono", className)}
    {...props}
  />
);

export const ToolBody = ({ className, ...props }: HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("p-3 text-[13px]", className)} {...props} />
);
