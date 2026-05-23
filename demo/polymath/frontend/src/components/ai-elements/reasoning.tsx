"use client";

import { useControllableState } from "@radix-ui/react-use-controllable-state";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { cjk } from "@streamdown/cjk";
import { code } from "@streamdown/code";
import { math } from "@streamdown/math";
import { mermaid } from "@streamdown/mermaid";
import { BrainIcon, ChevronDownIcon } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";
import {
  createContext,
  memo,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Streamdown } from "streamdown";

import { Shimmer } from "./shimmer";

interface ReasoningContextValue {
  isStreaming: boolean;
  isOpen: boolean;
  setIsOpen: (open: boolean) => void;
  duration: number | undefined;
  /** Whether the parent wants the one-line skim to render below the
   *  trigger when collapsed. */
  summary: boolean;
  /** Latest reasoning text — populated by `<ReasoningContent>` so
   *  `<Reasoning>` can derive a first-sentence preview without the
   *  caller having to pass the text twice. */
  text: string;
  setText: (value: string) => void;
}

const ReasoningContext = createContext<ReasoningContextValue | null>(null);

export const useReasoning = () => {
  const context = useContext(ReasoningContext);
  if (!context) {
    throw new Error("Reasoning components must be used within Reasoning");
  }
  return context;
};

export type ReasoningProps = ComponentProps<typeof Collapsible> & {
  isStreaming?: boolean;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  duration?: number;
  /** Show a one-line "skim mode" preview of the reasoning under the
   *  trigger when collapsed. Default `true`. Set `false` to opt out and
   *  get pure-collapsed behaviour. */
  summary?: boolean;
};

const AUTO_CLOSE_DELAY = 1000;
const MS_IN_S = 1000;
const SKIM_MAX_CHARS = 80;

export const Reasoning = memo(
  ({
    className,
    isStreaming = false,
    open,
    defaultOpen,
    onOpenChange,
    duration: durationProp,
    summary = true,
    children,
    ...props
  }: ReasoningProps) => {
    const resolvedDefaultOpen = defaultOpen ?? isStreaming;
    // Track if defaultOpen was explicitly set to false (to prevent auto-open)
    const isExplicitlyClosed = defaultOpen === false;

    const [isOpen, setIsOpen] = useControllableState<boolean>({
      defaultProp: resolvedDefaultOpen,
      onChange: onOpenChange,
      prop: open,
    });
    const [duration, setDuration] = useControllableState<number | undefined>({
      defaultProp: undefined,
      prop: durationProp,
    });

    const hasEverStreamedRef = useRef(isStreaming);
    const [hasAutoClosed, setHasAutoClosed] = useState(false);
    const startTimeRef = useRef<number | null>(null);
    // Reasoning content registers its current text here so the skim line
    // can render without callers having to pipe the text in twice.
    const [text, setText] = useState("");

    // Track when streaming starts and compute duration
    useEffect(() => {
      if (isStreaming) {
        hasEverStreamedRef.current = true;
        if (startTimeRef.current === null) {
          startTimeRef.current = Date.now();
        }
      } else if (startTimeRef.current !== null) {
        setDuration(Math.ceil((Date.now() - startTimeRef.current) / MS_IN_S));
        startTimeRef.current = null;
      }
    }, [isStreaming, setDuration]);

    // Auto-open when streaming starts (unless explicitly closed)
    useEffect(() => {
      if (isStreaming && !isOpen && !isExplicitlyClosed) {
        setIsOpen(true);
      }
    }, [isStreaming, isOpen, setIsOpen, isExplicitlyClosed]);

    // Auto-close when streaming ends (once only, and only if it ever streamed)
    useEffect(() => {
      if (
        hasEverStreamedRef.current &&
        !isStreaming &&
        isOpen &&
        !hasAutoClosed
      ) {
        const timer = setTimeout(() => {
          setIsOpen(false);
          setHasAutoClosed(true);
        }, AUTO_CLOSE_DELAY);

        return () => clearTimeout(timer);
      }
    }, [isStreaming, isOpen, setIsOpen, hasAutoClosed]);

    const handleOpenChange = useCallback(
      (newOpen: boolean) => {
        setIsOpen(newOpen);
      },
      [setIsOpen]
    );

    const contextValue = useMemo(
      () => ({
        duration,
        isOpen,
        isStreaming,
        setIsOpen,
        summary,
        text,
        setText,
      }),
      [duration, isOpen, isStreaming, setIsOpen, summary, text]
    );

    return (
      <ReasoningContext.Provider value={contextValue}>
        <Collapsible
          className={cn("not-prose mb-4", className)}
          onOpenChange={handleOpenChange}
          open={isOpen}
          {...props}
        >
          {children}
          <ReasoningSummaryLine />
        </Collapsible>
      </ReasoningContext.Provider>
    );
  }
);

export type ReasoningTriggerProps = ComponentProps<
  typeof CollapsibleTrigger
> & {
  getThinkingMessage?: (isStreaming: boolean, duration?: number) => ReactNode;
};

const defaultGetThinkingMessage = (isStreaming: boolean, duration?: number) => {
  if (isStreaming || duration === 0) {
    return <Shimmer duration={1}>Thinking...</Shimmer>;
  }
  if (duration === undefined) {
    return <p>Thought for a few seconds</p>;
  }
  return <p>Thought for {duration} seconds</p>;
};

export const ReasoningTrigger = memo(
  ({
    className,
    children,
    getThinkingMessage = defaultGetThinkingMessage,
    ...props
  }: ReasoningTriggerProps) => {
    const { isStreaming, isOpen, duration } = useReasoning();

    return (
      <CollapsibleTrigger
        className={cn(
          "flex w-full items-center gap-2 text-muted-foreground text-sm transition-colors hover:text-foreground",
          className
        )}
        {...props}
      >
        {children ?? (
          <>
            <BrainIcon className="size-4" />
            {getThinkingMessage(isStreaming, duration)}
            <ChevronDownIcon
              className={cn(
                "size-4 transition-transform",
                isOpen ? "rotate-180" : "rotate-0"
              )}
            />
          </>
        )}
      </CollapsibleTrigger>
    );
  }
);

export type ReasoningContentProps = ComponentProps<
  typeof CollapsibleContent
> & {
  children: string;
};

const streamdownPlugins = { cjk, code, math, mermaid };

export const ReasoningContent = memo(
  ({ className, children, ...props }: ReasoningContentProps) => {
    const { setText } = useReasoning();

    // Register the current text into context so the skim line can read
    // it. Effect (not direct call) keeps render pure.
    useEffect(() => {
      setText(children);
    }, [children, setText]);

    return (
      <CollapsibleContent
        className={cn(
          "mt-4 text-sm",
          "data-[state=closed]:fade-out-0 data-[state=closed]:slide-out-to-top-2 data-[state=open]:slide-in-from-top-2 text-muted-foreground outline-none data-[state=closed]:animate-out data-[state=open]:animate-in",
          className
        )}
        {...props}
      >
        <Streamdown plugins={streamdownPlugins}>{children}</Streamdown>
      </CollapsibleContent>
    );
  }
);

/**
 * Internal — renders a one-line preview of the reasoning under the
 * trigger when the block is collapsed. No-op while expanded or when
 * the parent set `summary={false}`. Pure consumer of context, so the
 * component tree can stay declarative.
 */
const ReasoningSummaryLine = memo(() => {
  const { summary, isOpen, text } = useReasoning();
  if (!summary || isOpen) return null;
  const skim = firstSentence(text);
  if (!skim) return null;
  return (
    <p className="mt-1 text-muted-foreground/80 text-xs leading-snug">
      {skim}
    </p>
  );
});
ReasoningSummaryLine.displayName = "ReasoningSummaryLine";

/**
 * Slice the first sentence out of `text`:
 *   - terminator candidates: `.`, `?`, `!`, `\n`
 *   - if a terminator falls within `SKIM_MAX_CHARS`, use it (inclusive)
 *   - else hard-truncate at `SKIM_MAX_CHARS` and append `…`
 *
 * Returns "" for empty / whitespace-only input.
 */
function firstSentence(text: string): string {
  const cleaned = text.trim();
  if (!cleaned) return "";

  let cutoff = -1;
  for (let i = 0; i < Math.min(cleaned.length, SKIM_MAX_CHARS); i++) {
    const ch = cleaned[i];
    if (ch === "." || ch === "?" || ch === "!" || ch === "\n") {
      cutoff = i;
      break;
    }
  }

  if (cutoff >= 0) {
    return cleaned.slice(0, cutoff + 1).trim();
  }
  if (cleaned.length <= SKIM_MAX_CHARS) {
    return cleaned;
  }
  return cleaned.slice(0, SKIM_MAX_CHARS).trimEnd() + "…";
}

Reasoning.displayName = "Reasoning";
ReasoningTrigger.displayName = "ReasoningTrigger";
ReasoningContent.displayName = "ReasoningContent";
