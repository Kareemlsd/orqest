"use client";

/**
 * Actions — hover-revealed action row for AI Elements messages.
 *
 * Mirrors the `Actions` / `Action` API from the AI Elements docs (the
 * Vercel registry doesn't ship a `actions.json` entry as of v1.x — the
 * pattern lives only in the docs site). Hand-authored here so the
 * `Message` primitive's group-hover reveal pattern works without
 * pulling in the rest of the registry.
 *
 * Designed to live inside an AI Elements `<Message>`, which sets a
 * Tailwind `group` class on its root. The row is `opacity-0` by default
 * and animates to `opacity-100` when the parent message is hovered — no
 * always-on toolbar visual noise (Polymath anti-AI-slop discipline).
 *
 * Each `<Action label="…">` wraps a ghost icon button with a tooltip,
 * so the affordance is keyboard-accessible *and* glance-readable.
 */
import type { ComponentProps } from "react";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export type ActionsProps = ComponentProps<"div">;

export const Actions = ({ className, children, ...props }: ActionsProps) => (
  <div
    className={cn(
      "flex items-center gap-1 opacity-0 transition-opacity duration-150",
      "group-hover:opacity-100 focus-within:opacity-100",
      className,
    )}
    {...props}
  >
    {children}
  </div>
);

export type ActionProps = ComponentProps<typeof Button> & {
  /** Text shown in the tooltip and used for `aria-label`. */
  label: string;
  /** Optional tooltip side override; defaults to bottom. */
  tooltipSide?: "top" | "right" | "bottom" | "left";
};

export const Action = ({
  label,
  tooltipSide = "bottom",
  className,
  size = "icon-xs",
  variant = "ghost",
  children,
  ...props
}: ActionProps) => (
  <TooltipProvider>
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          aria-label={label}
          className={cn("text-muted-foreground hover:text-foreground", className)}
          size={size}
          type="button"
          variant={variant}
          {...props}
        >
          {children}
        </Button>
      </TooltipTrigger>
      <TooltipContent side={tooltipSide}>
        <span className="text-[11px]">{label}</span>
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>
);
