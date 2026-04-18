"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { useMemo } from "react";
import { BookOpen, ExternalLink } from "lucide-react";
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
} from "@/components/ai-elements/conversation";
import {
  Message,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message";
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolInput,
  ToolOutput,
} from "@/components/ai-elements/tool";
import {
  PromptInput,
  PromptInputTextarea,
  PromptInputSubmit,
} from "@/components/ai-elements/prompt-input";
import { DemoShell } from "@/components/demo-shell";

type SourceEntry = {
  index: number;
  title: string;
  url: string;
};

/**
 * Parse the agent's output for a **Sources** section of the form:
 *   **Sources**
 *   [1] Title — URL
 *   [2] Title — URL
 */
function parseSources(text: string): SourceEntry[] {
  const sourcesMatch = text.match(/\*\*Sources\*\*\s*\n([\s\S]*?)$/);
  if (!sourcesMatch) return [];
  const lines = sourcesMatch[1].split("\n");
  const sources: SourceEntry[] = [];
  for (const line of lines) {
    const m = line.match(/\[(\d+)\]\s*(.+?)\s*[—–-]\s*(https?:\S+)/);
    if (m) {
      sources.push({
        index: parseInt(m[1], 10),
        title: m[2].trim(),
        url: m[3].trim(),
      });
    }
  }
  return sources;
}

/** Strip the **Sources** section from text so it's not duplicated in the chat. */
function stripSources(text: string): string {
  return text.replace(/\*\*Sources\*\*\s*\n[\s\S]*$/, "").trim();
}

export default function ResearchDemo() {
  const { messages, sendMessage, status, error } = useChat({
    transport: new DefaultChatTransport({ api: "/api/demos/research/chat" }),
  });

  // Accumulate sources from all assistant messages
  const allSources = useMemo(() => {
    const seen = new Map<string, SourceEntry>();
    for (const m of messages) {
      if (m.role !== "assistant") continue;
      const text = m.parts
        .filter((p) => p.type === "text")
        .map((p) => ("text" in p ? p.text : ""))
        .join("\n");
      for (const source of parseSources(text)) {
        seen.set(source.url, source);
      }
    }
    return Array.from(seen.values());
  }, [messages]);

  const handleSubmit = (message: { text?: string }) => {
    const text = message.text?.trim();
    if (!text) return;
    sendMessage({ text });
  };

  return (
    <DemoShell
      title="Research Assistant"
      subtitle="Web search + inline citations — Perplexity-style"
    >
      <div className="flex h-full">
        {/* Left: chat */}
        <div className="flex-1 flex flex-col border-r border-border/60">
          <div className="flex-1 overflow-hidden">
            <Conversation className="h-full">
              <ConversationContent className="px-6 py-6">
                {messages.length === 0 && (
                  <ConversationEmptyState
                    title="Ask a research question"
                    description='Try: "Pros and cons of nuclear power in 2026" · "State of quantum computing" · "Latest on agentic AI"'
                  />
                )}

                {messages.map((message) => (
                  <Message key={message.id} from={message.role}>
                    <MessageContent>
                      {message.parts.map((part, index) => {
                        if (part.type === "text") {
                          const cleaned = stripSources(part.text);
                          return (
                            <MessageResponse key={`${message.id}-text-${index}`}>
                              {cleaned}
                            </MessageResponse>
                          );
                        }

                        if ("toolCallId" in part) {
                          return (
                            <Tool key={part.toolCallId}>
                              <ToolHeader
                                type={part.type}
                                state={part.state}
                              />
                              <ToolContent>
                                <ToolInput input={part.input} />
                                {(part.state === "output-available" ||
                                  part.state === "output-error") && (
                                  <ToolOutput
                                    output={part.output as string | undefined}
                                    errorText={part.errorText}
                                  />
                                )}
                              </ToolContent>
                            </Tool>
                          );
                        }

                        return null;
                      })}
                    </MessageContent>
                  </Message>
                ))}

                {error && (
                  <div className="rounded-md border border-destructive bg-destructive/10 p-3 text-sm text-destructive">
                    Error: {error.message}
                  </div>
                )}
              </ConversationContent>
            </Conversation>
          </div>

          <div className="border-t border-border/60 p-4">
            <PromptInput onSubmit={handleSubmit}>
              <PromptInputTextarea placeholder="Ask a research question..." />
              <PromptInputSubmit status={status} />
            </PromptInput>
          </div>
        </div>

        {/* Right: sources */}
        <div className="w-[360px] flex flex-col bg-background">
          <div className="border-b border-border/60 px-4 py-3">
            <h2 className="text-sm font-semibold flex items-center gap-2">
              <BookOpen className="w-4 h-4" />
              Sources
            </h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              {allSources.length === 0
                ? "No sources yet"
                : `${allSources.length} source${allSources.length === 1 ? "" : "s"} cited`}
            </p>
          </div>

          <div className="flex-1 overflow-auto p-4">
            {allSources.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center">
                <div className="w-12 h-12 rounded-md border border-border/60 flex items-center justify-center mb-4 text-muted-foreground">
                  <BookOpen className="w-5 h-5" />
                </div>
                <p className="text-sm font-medium">Sources panel</p>
                <p className="text-xs text-muted-foreground mt-1 max-w-xs">
                  Citations from the agent&apos;s research will accumulate here
                  as you chat.
                </p>
              </div>
            ) : (
              <div className="space-y-2">
                {allSources.map((source) => (
                  <a
                    key={source.url}
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="group flex items-start gap-3 p-3 rounded-md border border-border/60 bg-card hover:border-border transition-colors"
                  >
                    <div className="w-6 h-6 rounded bg-muted text-xs font-mono flex items-center justify-center flex-shrink-0 text-muted-foreground group-hover:text-foreground">
                      {source.index}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium leading-snug group-hover:underline">
                        {source.title}
                      </p>
                      <p className="text-xs text-muted-foreground mt-1 truncate">
                        {new URL(source.url).hostname}
                      </p>
                    </div>
                    <ExternalLink className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0 mt-0.5" />
                  </a>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </DemoShell>
  );
}
