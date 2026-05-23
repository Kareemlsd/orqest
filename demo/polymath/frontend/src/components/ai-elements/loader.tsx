"use client";

/**
 * Loader — minimal animated spinner used while a tool is streaming input.
 *
 * The AI Elements `loader` component is not in the registry as of
 * 2026-04-25, so this is an inline equivalent matching the AI SDK
 * idiom (Lucide `Loader2Icon` rotating). Reuses Polymath's accent
 * color via the `text-accent` Tailwind token.
 */
import { Loader2Icon } from "lucide-react";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export type LoaderProps = ComponentProps<typeof Loader2Icon> & {
  size?: number;
};

export const Loader = ({ className, size = 16, ...props }: LoaderProps) => (
  <Loader2Icon
    className={cn("animate-spin text-accent", className)}
    size={size}
    {...props}
  />
);
