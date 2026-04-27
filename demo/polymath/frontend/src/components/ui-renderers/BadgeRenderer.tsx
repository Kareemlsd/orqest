"use client";

/**
 * BadgeRenderer — small inline pill. Tones map to the workspace's
 * accent / muted / success / warning / destructive token families with
 * a low-saturation background and a saturated foreground.
 *
 * Icons resolve through a curated lucide-react switch — keeps the
 * bundle small (no `dynamic-icon` round trip) at the cost of a fixed
 * vocabulary. If the agent emits an unknown icon name, we silently
 * drop it (label still renders).
 */
import { cn } from "@/lib/utils";
import {
  AlertTriangle,
  Check,
  CheckCircle,
  CircleAlert,
  CircleHelp,
  Clock,
  ExternalLink,
  FileText,
  Info,
  Search,
  Sparkles,
  Star,
  X,
  XCircle,
  Zap,
  type LucideIcon,
} from "lucide-react";

import { registerRenderer, type UIRenderer } from "./registry";

interface BadgeData {
  label?: string;
  tone?: "default" | "muted" | "accent" | "success" | "warning" | "destructive";
  icon?: string;
}

const TONE_CLASSES: Record<NonNullable<BadgeData["tone"]>, string> = {
  default:
    "bg-surface-elevated text-foreground border border-border-default",
  muted: "bg-muted text-muted-foreground",
  accent: "bg-accent/15 text-accent",
  success: "bg-[var(--color-success)]/15 text-[var(--color-success)]",
  warning: "bg-[var(--color-warning)]/15 text-[var(--color-warning)]",
  destructive: "bg-destructive/15 text-destructive",
};

const ICON_MAP: Record<string, LucideIcon> = {
  check: Check,
  "check-circle": CheckCircle,
  x: X,
  "x-circle": XCircle,
  info: Info,
  warning: AlertTriangle,
  "alert-triangle": AlertTriangle,
  "alert-circle": CircleAlert,
  help: CircleHelp,
  clock: Clock,
  search: Search,
  sparkles: Sparkles,
  star: Star,
  zap: Zap,
  link: ExternalLink,
  "external-link": ExternalLink,
  file: FileText,
  "file-text": FileText,
};

const BadgeRenderer: UIRenderer<BadgeData> = (spec) => {
  const data = spec.data ?? {};
  const tone = data.tone ?? "default";
  const label = data.label ?? "";
  const Icon = data.icon ? ICON_MAP[data.icon.toLowerCase()] : undefined;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[11px] leading-none",
        TONE_CLASSES[tone] ?? TONE_CLASSES.default,
      )}
    >
      {Icon && <Icon size={11} aria-hidden />}
      {label}
    </span>
  );
};

registerRenderer("badge", BadgeRenderer);
export default BadgeRenderer;
