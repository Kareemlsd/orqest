"use client";

import type { ComponentProps } from "react";
import { StickToBottom } from "use-stick-to-bottom";

import { cn } from "@/lib/utils";

/**
 * Thin wrapper around use-stick-to-bottom for the chat scroll container.
 * Adapted from numatics-ai; streamdown-specific bits (download, scroll
 * button) dropped for Phase 0.
 */
export const Conversation = ({
  className,
  ...props
}: ComponentProps<typeof StickToBottom>) => (
  <StickToBottom
    className={cn("relative flex-1 overflow-y-hidden", className)}
    initial="smooth"
    resize="smooth"
    role="log"
    {...props}
  />
);

export const ConversationContent = ({
  className,
  ...props
}: ComponentProps<typeof StickToBottom.Content>) => (
  <StickToBottom.Content className={cn("flex flex-col gap-6 p-4", className)} {...props} />
);
