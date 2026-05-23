"use client";

/**
 * useChat — AI SDK v6 chat hook wired to the Polymath backend.
 *
 * Shape reference: numatics-ai/src/hooks/useChatV3.ts. The FEA-specific
 * DataChunk demultiplexing (quality_report / geo_diff / sandbox_output)
 * is gone. Instead the hook exposes a raw `messages` list plus optional
 * `onEvent` callback for sidecar events — see hooks/useSidecar.ts.
 *
 * Hydration note: per Vercel AI SDK v6, the `messages` option on
 * `useChat` is seed-only. To rehydrate the transcript from the backend
 * on mount, we GET /sessions/{sid}/messages and push via `setMessages`.
 */
import { useChat as useChatSDK } from "@ai-sdk/react";
import { DefaultChatTransport, type UIMessage } from "ai";
import { useEffect, useMemo, useRef, useState } from "react";

import { backendBase } from "@/lib/api";

interface UseChatOptions {
  sessionId: string;
}

interface PersistedMessage {
  id: string;
  role: "user" | "assistant" | string;
  content: string;
  created_at?: string | null;
}

export function useChat({ sessionId }: UseChatOptions) {
  const base = useMemo(() => backendBase(), []);
  const sessionIdRef = useRef(sessionId);
  sessionIdRef.current = sessionId;

  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: `${base}/sessions/${sessionId}/chat/stream`,
        headers: () => ({
          "X-Session-Id": sessionIdRef.current,
        }),
      }),
    [base, sessionId],
  );

  const { messages, sendMessage, status, error, stop, setMessages } = useChatSDK({
    transport,
  });

  const [isLoadingHistory, setIsLoadingHistory] = useState(true);

  // Rehydrate transcript from backend on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(`${base}/sessions/${sessionId}/messages`);
        if (!resp.ok) return;
        const payload: { messages: PersistedMessage[] } = await resp.json();
        if (cancelled) return;
        const hydrated: UIMessage[] = payload.messages.map((m) => ({
          id: m.id,
          role: m.role === "assistant" ? "assistant" : (m.role as UIMessage["role"]),
          parts: [{ type: "text", text: m.content }],
        }));
        setMessages(hydrated);
      } catch {
        // Empty transcript is a valid state (new session).
      } finally {
        if (!cancelled) setIsLoadingHistory(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [base, sessionId, setMessages]);

  return {
    messages,
    status,
    error,
    sendMessage,
    stop,
    isLoadingHistory,
  };
}
