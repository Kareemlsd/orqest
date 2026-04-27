"use client";

import type { HTMLAttributes } from "react";
import type { UIMessage } from "ai";

import { cn } from "@/lib/utils";

/**
 * AI Elements Message wrapper. Role distinction is applied by the caller
 * via ChatPane's wrapper class — this component only tags the role for
 * the CSS group selector.
 */
export type MessageProps = HTMLAttributes<HTMLDivElement> & {
  from: UIMessage["role"];
};

export const Message = ({ className, from, ...props }: MessageProps) => (
  <div
    className={cn(
      "group flex w-full flex-col gap-2",
      from === "user" ? "is-user" : "is-assistant",
      className,
    )}
    {...props}
  />
);
