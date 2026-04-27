"use client";

/**
 * SessionContext — header chip that exposes cumulative session token
 * usage via the AI Elements `<Context>` ring.
 *
 * Renders nothing on a fresh session (totalTokens === 0). Once activity
 * arrives, shows a tight `tokens <ring>` pair right-aligned in the
 * session header strip (between the wordmark and the connection dot).
 *
 * The hover card surfaces input / output / cache breakdowns courtesy
 * of the AI Elements primitive's body slots.
 */
import type { LanguageModelUsage } from "ai";

import {
  Context,
  ContextCacheUsage,
  ContextContent,
  ContextContentBody,
  ContextContentFooter,
  ContextContentHeader,
  ContextInputUsage,
  ContextOutputUsage,
  ContextTrigger,
} from "@/components/ai-elements/context";
import { useSessionMetrics } from "@/hooks/useSessionMetrics";

interface SessionContextProps {
  sessionId: string;
  /** Override the model context window. Default = 200k (Claude). */
  maxTokens?: number;
}

const DEFAULT_MAX_TOKENS = 200_000;

export function SessionContext({
  sessionId,
  maxTokens = DEFAULT_MAX_TOKENS,
}: SessionContextProps) {
  const m = useSessionMetrics(sessionId);

  // Fresh session — no usage yet, suppress the chip entirely. We don't
  // want a "0 / 200000" sitting in the header doing nothing.
  if (m.totalTokens === 0) return null;

  // The Context primitive's hover card consumes a `LanguageModelUsage`
  // shape (camelCase, with nested {input,output}TokenDetails). It also
  // duck-reads `cachedInputTokens` on the usage object directly (older
  // ai-sdk shape), so we satisfy both surfaces by extending the typed
  // base with the legacy flat field. Cast through `LanguageModelUsage &
  // { cachedInputTokens?: number }` keeps strict typing happy.
  const usage = {
    inputTokens: m.inputTokens,
    outputTokens: m.outputTokens,
    totalTokens: m.totalTokens,
    inputTokenDetails: {
      noCacheTokens: Math.max(0, m.inputTokens - m.cacheReadTokens),
      cacheReadTokens: m.cacheReadTokens,
      cacheWriteTokens: m.cacheWriteTokens,
    },
    outputTokenDetails: {
      textTokens: m.outputTokens,
      reasoningTokens: 0,
    },
    cachedInputTokens: m.cacheReadTokens,
  } as LanguageModelUsage & { cachedInputTokens?: number };

  return (
    <div className="flex items-center gap-1.5">
      <span className="font-mono text-[10px] text-muted-foreground">tokens</span>
      <Context maxTokens={maxTokens} usage={usage} usedTokens={m.totalTokens}>
        <ContextTrigger className="h-6 gap-1 px-1.5 text-[10px]" />
        <ContextContent>
          <ContextContentHeader />
          <ContextContentBody>
            <div className="space-y-1.5">
              <ContextInputUsage />
              <ContextOutputUsage />
              <ContextCacheUsage />
            </div>
          </ContextContentBody>
          <ContextContentFooter>
            <span className="text-muted-foreground">Turns</span>
            <span className="font-mono">{m.turns}</span>
          </ContextContentFooter>
        </ContextContent>
      </Context>
    </div>
  );
}
