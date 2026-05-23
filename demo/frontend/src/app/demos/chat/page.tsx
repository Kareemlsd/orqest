"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
  ConversationScrollButton,
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
import {
  Reasoning,
  ReasoningContent,
  ReasoningTrigger,
} from "@/components/ai-elements/reasoning";
import { DemoShell } from "@/components/demo-shell";

export default function ChatDemo() {
  const { messages, sendMessage, status, error } = useChat({
    transport: new DefaultChatTransport({ api: "/api/demos/chat/chat" }),
  });

  const handleSubmit = (message: { text?: string }) => {
    const text = message.text?.trim();
    if (!text) return;
    sendMessage({ text });
  };

  return (
    <DemoShell
      title="Streaming Chat"
      subtitle="The foundation — streaming tokens and tool calls via useChat"
    >
      <div className="flex flex-col h-full">
        <div className="flex-1 overflow-hidden">
          <Conversation className="h-full">
            <ConversationContent className="max-w-3xl mx-auto px-6 py-6">
              {messages.length === 0 && (
                <ConversationEmptyState
                  title="Ask the Orqest research assistant"
                  description='Try: "What time is it?" or "Calculate 42 * 17" or "Analyze quantum computing"'
                />
              )}

              {messages.map((message) => (
                <Message key={message.id} from={message.role}>
                  <MessageContent>
                    {message.parts.map((part, index) => {
                      if (part.type === "text") {
                        return (
                          <MessageResponse key={`${message.id}-text-${index}`}>
                            {part.text}
                          </MessageResponse>
                        );
                      }

                      if (part.type === "reasoning") {
                        return (
                          <Reasoning
                            key={`${message.id}-reasoning-${index}`}
                            isStreaming={status === "streaming"}
                          >
                            <ReasoningTrigger />
                            <ReasoningContent>{part.text}</ReasoningContent>
                          </Reasoning>
                        );
                      }

                      if ("toolCallId" in part) {
                        return (
                          <Tool key={part.toolCallId}>
                            <ToolHeader type={part.type} state={part.state} />
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
            <ConversationScrollButton />
          </Conversation>
        </div>

        <div className="border-t border-border/60 p-4">
          <PromptInput onSubmit={handleSubmit} className="max-w-3xl mx-auto">
            <PromptInputTextarea placeholder="Ask the Orqest agent anything..." />
            <PromptInputSubmit status={status} />
          </PromptInput>
        </div>
      </div>
    </DemoShell>
  );
}
