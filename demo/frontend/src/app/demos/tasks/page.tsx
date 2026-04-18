"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { useMemo } from "react";
import { CheckCircle2, Circle, Loader2, AlertCircle } from "lucide-react";
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
  PromptInput,
  PromptInputTextarea,
  PromptInputSubmit,
} from "@/components/ai-elements/prompt-input";
import { DemoShell } from "@/components/demo-shell";

type TaskStatus = "pending" | "running" | "complete" | "error";

type TaskStep = {
  index?: number;
  description?: string;
  status?: TaskStatus;
  result?: string;
};

type PartialPlan = {
  goal?: string;
  steps?: TaskStep[];
  summary?: string;
};

/**
 * Extract the most recent TaskPlan from the message list. pydantic-ai
 * returns structured output via a tool call called `final_result` whose
 * `input` field streams as partial JSON (filling in keys as tokens arrive).
 */
function latestPlan(messages: ReturnType<typeof useChat>["messages"]): {
  plan: PartialPlan | null;
  isStreaming: boolean;
} {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role !== "assistant") continue;
    for (const part of m.parts) {
      if (
        "toolCallId" in part &&
        typeof part.type === "string" &&
        part.type.startsWith("tool-final_result")
      ) {
        const input = (part as { input?: unknown }).input as
          | PartialPlan
          | undefined;
        const isStreaming =
          part.state === "input-streaming" || part.state === "input-available";
        return { plan: input ?? null, isStreaming };
      }
    }
  }
  return { plan: null, isStreaming: false };
}

function StatusIcon({ status }: { status: TaskStatus | undefined }) {
  if (status === "complete") {
    return <CheckCircle2 className="w-4 h-4 text-teal-500 flex-shrink-0" />;
  }
  if (status === "running") {
    return (
      <Loader2 className="w-4 h-4 text-blue-500 flex-shrink-0 animate-spin" />
    );
  }
  if (status === "error") {
    return <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0" />;
  }
  return (
    <Circle className="w-4 h-4 text-muted-foreground flex-shrink-0" />
  );
}

export default function TaskPlanner() {
  const { messages, sendMessage, status, error } = useChat({
    transport: new DefaultChatTransport({ api: "/api/demos/tasks/chat" }),
  });

  const { plan, isStreaming } = useMemo(() => latestPlan(messages), [messages]);
  const steps = plan?.steps ?? [];
  const completedCount = steps.filter((s) => s.status === "complete").length;

  const handleSubmit = (message: { text?: string }) => {
    const text = message.text?.trim();
    if (!text) return;
    sendMessage({ text });
  };

  return (
    <DemoShell
      title="Task Planner"
      subtitle="Goal decomposition + live progress — structured output via pydantic-ai"
    >
      <div className="flex h-full">
        {/* Left: chat */}
        <div className="flex-1 flex flex-col border-r border-border/60">
          <div className="flex-1 overflow-hidden">
            <Conversation className="h-full">
              <ConversationContent className="px-6 py-6">
                {messages.length === 0 && (
                  <ConversationEmptyState
                    title="Give the agent a goal"
                    description='Try: "Plan a weekend trip to Kyoto" · "Launch a coffee shop" · "Write a novel in 30 days"'
                  />
                )}

                {messages.map((message) => (
                  <Message key={message.id} from={message.role}>
                    <MessageContent>
                      {message.role === "user" &&
                        message.parts.map((part, index) => {
                          if (part.type === "text") {
                            return (
                              <MessageResponse
                                key={`${message.id}-text-${index}`}
                              >
                                {part.text}
                              </MessageResponse>
                            );
                          }
                          return null;
                        })}

                      {/* For assistant messages, show a concise summary instead of
                          the raw JSON tool call. The detailed plan lives on the right. */}
                      {message.role === "assistant" &&
                        (() => {
                          const summary = message.parts
                            .filter(
                              (p): p is typeof p & { input: PartialPlan } =>
                                "toolCallId" in p &&
                                typeof p.type === "string" &&
                                p.type.startsWith("tool-final_result")
                            )
                            .map((p) => p.input?.summary)
                            .filter(Boolean)
                            .join("\n\n");
                          if (summary) {
                            return <MessageResponse>{summary}</MessageResponse>;
                          }
                          return (
                            <p className="text-xs text-muted-foreground italic">
                              Planning… see the task tree on the right.
                            </p>
                          );
                        })()}
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
              <PromptInputTextarea placeholder="Give the agent a goal..." />
              <PromptInputSubmit status={status} />
            </PromptInput>
          </div>
        </div>

        {/* Right: task tree */}
        <div className="w-[420px] flex flex-col bg-background">
          <div className="border-b border-border/60 px-4 py-3">
            <h2 className="text-sm font-semibold">Plan</h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              {steps.length === 0
                ? "No active plan"
                : `${completedCount} of ${steps.length} complete${
                    isStreaming ? " · streaming…" : ""
                  }`}
            </p>
            {plan?.goal && (
              <p className="text-sm font-medium mt-2 leading-snug">
                {plan.goal}
              </p>
            )}
          </div>

          <div className="flex-1 overflow-auto p-4">
            {steps.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center">
                <div className="w-12 h-12 rounded-md border border-border/60 flex items-center justify-center mb-4 text-muted-foreground">
                  <Circle className="w-5 h-5" />
                </div>
                <p className="text-sm font-medium">Task tree</p>
                <p className="text-xs text-muted-foreground mt-1 max-w-xs">
                  The agent will decompose your goal into steps and execute
                  each one live.
                </p>
              </div>
            ) : (
              <div className="space-y-2">
                {steps.map((step, i) => (
                  <div
                    key={step.index ?? i}
                    className="flex items-start gap-3 p-3 rounded-md border border-border/60 bg-card"
                  >
                    <StatusIcon status={step.status} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-mono text-muted-foreground">
                          Step {step.index ?? i + 1}
                        </p>
                        <span
                          className={`text-[10px] uppercase tracking-wider font-semibold ${
                            step.status === "complete"
                              ? "text-teal-500"
                              : step.status === "running"
                                ? "text-blue-500"
                                : step.status === "error"
                                  ? "text-red-500"
                                  : "text-muted-foreground"
                          }`}
                        >
                          {step.status ?? "pending"}
                        </span>
                      </div>
                      {step.description && (
                        <p className="text-sm mt-1 leading-snug">
                          {step.description}
                        </p>
                      )}
                      {step.result && (
                        <p className="text-xs text-muted-foreground mt-1.5 italic border-l-2 border-border/60 pl-2">
                          {step.result}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </DemoShell>
  );
}
