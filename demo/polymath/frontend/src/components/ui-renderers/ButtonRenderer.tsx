"use client";

/**
 * ButtonRenderer — interactive primitive that fires a backend event on
 * click via `ctx.emitEvent(event_name, event_payload)`.
 *
 * Icons share the `BadgeRenderer` icon vocabulary intentionally: the
 * agent gets one symbol set across primitives instead of having to
 * remember which name space each renderer uses.
 *
 * `pending` state suppresses double-fire while the POST is in flight —
 * agents emitting buttons usually expect at-most-once dispatch per
 * physical click.
 */
import { useCallback, useState } from "react";

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

interface ButtonData {
  label?: string;
  event_name?: string;
  event_payload?: Record<string, unknown>;
  variant?: "primary" | "secondary" | "ghost" | "destructive";
  icon?: string;
  disabled?: boolean;
}

const VARIANT_CLASSES: Record<NonNullable<ButtonData["variant"]>, string> = {
  primary:
    "bg-accent text-white hover:bg-accent-hover",
  secondary:
    "border border-border-default bg-surface-elevated text-foreground hover:bg-muted",
  ghost: "bg-transparent text-foreground hover:bg-muted",
  destructive:
    "bg-destructive text-destructive-foreground hover:bg-destructive/90",
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

const ButtonRenderer: UIRenderer<ButtonData> = (spec, ctx) => {
  // Wrap as a component so we can hold per-instance `pending` state
  // without violating the rules-of-hooks contract on a function-style
  // renderer.
  return <ButtonImpl spec={spec} ctx={ctx} />;
};

function ButtonImpl({
  spec,
  ctx,
}: {
  spec: { component_id: string; data?: ButtonData };
  ctx: { emitEvent: (name: string, payload: Record<string, unknown>) => Promise<void> };
}) {
  const data = spec.data ?? {};
  const variant = data.variant ?? "primary";
  const label = data.label ?? "Submit";
  const disabled = !!data.disabled;
  const Icon = data.icon ? ICON_MAP[data.icon.toLowerCase()] : undefined;

  const [pending, setPending] = useState(false);

  const onClick = useCallback(async () => {
    if (pending || disabled) return;
    if (!data.event_name) return;
    setPending(true);
    try {
      await ctx.emitEvent(data.event_name, data.event_payload ?? {});
    } finally {
      setPending(false);
    }
  }, [pending, disabled, data.event_name, data.event_payload, ctx]);

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || pending}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 font-mono text-[12px] leading-none transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1",
        "disabled:cursor-not-allowed disabled:opacity-60",
        VARIANT_CLASSES[variant] ?? VARIANT_CLASSES.primary,
      )}
    >
      {Icon && <Icon size={12} aria-hidden />}
      <span>{label}</span>
    </button>
  );
}

registerRenderer("button", ButtonRenderer);
export default ButtonRenderer;
