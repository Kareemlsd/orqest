"use client";

/**
 * ConfidenceBadge — tight inline pill that surfaces an assistant
 * message's self-rated confidence.
 *
 * Drawn as a mono-font pill: `94%` body in the foreground colour, a
 * thin left border in one of three accent ramps (high → accent-teal,
 * medium → muted-foreground, low → warning), and a hover tooltip that
 * unfolds the full {@link MetacognitionFrame} — uncertainty targets,
 * capability_boundary flag, protocol name.
 *
 * Designed to sit *inline* alongside the assistant role label rather
 * than on a dedicated row above the message body — Stream 2 polish
 * shrinks the badge so it carries no extra padding and never adds a
 * blank vertical band when present.
 *
 * Renders nothing when `frame` is null (silent on messages whose tool
 * calls didn't return an `EnrichedOutput` — the badge would just be
 * dishonest noise then).
 *
 * Anti-AI-slop discipline: no animated robots, no rainbow gradients,
 * no emoji. The badge is a quiet editorial annotation that *adds*
 * information without competing with the message body.
 */
import { cn } from "@/lib/utils";

import type { MetacognitionFrame } from "@/hooks/useMetacognition";

interface ConfidenceBadgeProps {
  frame: MetacognitionFrame | null;
}

export function ConfidenceBadge({ frame }: ConfidenceBadgeProps) {
  if (!frame || frame.confidence === null) return null;

  const pct = Math.round(frame.confidence * 100);
  const tier = tierOf(frame.confidence, frame.capability_boundary);

  return (
    <span
      className={cn(
        // Tighter inline geometry — no padding wasted on the y-axis,
        // sits cleanly inside the role-label row.
        "inline-flex items-center gap-1 rounded-sm border border-l-2",
        "px-1 py-px font-mono text-[10px] leading-none",
        "bg-surface-elevated/60 cursor-help select-none transition-colors",
        TIER_STYLES[tier],
      )}
      title={renderTooltip(frame, pct, tier)}
    >
      {pct}%
      {frame.capability_boundary && (
        <span aria-hidden className="text-warning">·</span>
      )}
    </span>
  );
}

type Tier = "high" | "medium" | "low" | "boundary";

function tierOf(confidence: number, boundary: boolean): Tier {
  if (boundary) return "boundary";
  if (confidence >= 0.8) return "high";
  if (confidence >= 0.55) return "medium";
  return "low";
}

const TIER_STYLES: Record<Tier, string> = {
  high: "border-accent/60 text-accent",
  medium: "border-muted-foreground/40 text-muted-foreground",
  low: "border-warning/60 text-warning",
  boundary: "border-warning text-warning",
};

function renderTooltip(
  frame: MetacognitionFrame,
  pct: number,
  tier: Tier,
): string {
  const lines: string[] = [`Self-rated confidence: ${pct}%`];
  if (frame.capability_boundary) {
    lines.push(
      "Capability boundary: yes — the agent flagged this as outside its trustworthy range.",
    );
  }
  if (frame.uncertainty_targets.length > 0) {
    lines.push(`Uncertain about: ${frame.uncertainty_targets.join(", ")}`);
  }
  if (frame.protocol) {
    lines.push(`Protocol: ${frame.protocol}`);
  }
  lines.push(`(tier: ${tier})`);
  return lines.join("\n");
}
