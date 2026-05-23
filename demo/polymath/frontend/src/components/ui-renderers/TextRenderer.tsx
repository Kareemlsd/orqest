"use client";

/**
 * TextRenderer — typographic primitive. Variants map to Polymath's
 * type scale (matches the serif / mono pairings used elsewhere in the
 * workspace; see `Message.tsx` for the same heading sizes).
 *
 * `code-inline` mirrors the inline `<code>` styling from the chat
 * markdown override so a code-fragment text component reads as part of
 * the same family.
 */
import { cn } from "@/lib/utils";

import { registerRenderer, type UIRenderer } from "./registry";

interface TextData {
  content?: string;
  variant?: "heading" | "subheading" | "body" | "caption" | "code-inline";
  tone?: "default" | "muted" | "accent" | "destructive";
}

const VARIANT_CLASSES: Record<NonNullable<TextData["variant"]>, string> = {
  heading: "font-serif text-[18px] font-medium leading-tight",
  subheading: "font-serif text-[15px] leading-snug",
  body: "text-[13px] leading-relaxed",
  caption: "font-mono text-[11px] text-muted-foreground",
  "code-inline":
    "bg-surface-code text-accent text-[11px] font-mono px-1.5 py-0.5 rounded-[4px] inline",
};

const TONE_CLASSES: Record<NonNullable<TextData["tone"]>, string> = {
  default: "",
  muted: "text-muted-foreground",
  accent: "text-accent",
  destructive: "text-destructive",
};

const TextRenderer: UIRenderer<TextData> = (spec) => {
  const data = spec.data ?? {};
  const variant = data.variant ?? "body";
  const tone = data.tone ?? "default";
  const content = data.content ?? "";

  const variantClass = VARIANT_CLASSES[variant] ?? VARIANT_CLASSES.body;
  // The caption variant carries its own tone; explicit `tone="muted"`
  // is allowed to no-op rather than fight the variant.
  const toneClass =
    variant === "caption" && tone === "default" ? "" : TONE_CLASSES[tone] ?? "";

  if (variant === "heading") {
    return <h2 className={cn(variantClass, toneClass)}>{content}</h2>;
  }
  if (variant === "subheading") {
    return <h3 className={cn(variantClass, toneClass)}>{content}</h3>;
  }
  if (variant === "code-inline") {
    return <code className={cn(variantClass, toneClass)}>{content}</code>;
  }
  return <p className={cn(variantClass, toneClass)}>{content}</p>;
};

registerRenderer("text", TextRenderer);
export default TextRenderer;
