"use client";

/**
 * TakeoverButton — pause the agent and grant the user interactive
 * control of the sandbox viewport. Flips to "Resume" while takeover
 * is active.
 */
import { HandIcon, PlayIcon } from "lucide-react";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useTakeover } from "@/hooks/useTakeover";

export function TakeoverButton({ sessionId }: { sessionId: string }) {
  const { active, pending, take, release } = useTakeover(sessionId);
  const onClick = active ? release : take;
  const Icon = active ? PlayIcon : HandIcon;
  const label = active ? "Resume" : "Takeover";
  const tip = active
    ? "Hand control back to the agent."
    : "Pause the agent and drive the sandbox yourself.";
  const accent = active
    ? "border-accent text-accent bg-accent/10"
    : "border-border-default text-foreground bg-surface-elevated";

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={onClick}
            disabled={pending}
            className={`inline-flex items-center gap-1.5 h-7 px-2.5 rounded-sm border ${accent} text-[11px] font-mono transition-colors hover:bg-surface-hover disabled:opacity-60 disabled:cursor-wait`}
          >
            <Icon className="size-3.5" />
            {label}
          </button>
        </TooltipTrigger>
        <TooltipContent>{tip}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
