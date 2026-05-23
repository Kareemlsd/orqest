"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { useState, useRef } from "react";
import { Paperclip, X } from "lucide-react";
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
  PromptInputTools,
  PromptInputButton,
} from "@/components/ai-elements/prompt-input";
import {
  Suggestion,
  Suggestions,
} from "@/components/ai-elements/suggestion";
import { DemoShell } from "@/components/demo-shell";

type Attachment = {
  id: string;
  name: string;
  mediaType: string;
  url: string; // data URL
};

const SUGGESTIONS = [
  "Describe this image in detail",
  "What objects do you see?",
  "Extract any visible text",
  "Suggest edits or improvements",
];

export default function MultimodalDemo() {
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const { messages, sendMessage, status, error } = useChat({
    transport: new DefaultChatTransport({ api: "/api/demos/multimodal/chat" }),
  });

  const addFiles = async (files: FileList | null) => {
    if (!files) return;
    const newAttachments: Attachment[] = [];
    for (const file of Array.from(files)) {
      if (!file.type.startsWith("image/")) continue;
      const url = await new Promise<string>((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result as string);
        reader.readAsDataURL(file);
      });
      newAttachments.push({
        id: crypto.randomUUID(),
        name: file.name,
        mediaType: file.type,
        url,
      });
    }
    setAttachments((prev) => [...prev, ...newAttachments]);
  };

  const removeAttachment = (id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  };

  const send = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed && attachments.length === 0) return;

    const files = attachments.map((a) => ({
      type: "file" as const,
      filename: a.name,
      mediaType: a.mediaType,
      url: a.url,
    }));

    sendMessage({
      text: trimmed || "What do you see in this image?",
      files,
    });
    setAttachments([]);
  };

  const handleSubmit = (message: { text?: string }) => {
    send(message.text ?? "");
  };

  return (
    <DemoShell
      title="Multimodal Analyst"
      subtitle="Upload images + ask questions — pydantic-ai vision via VercelAIAdapter"
    >
      <div className="flex flex-col h-full">
        <div className="flex-1 overflow-hidden">
          <Conversation className="h-full">
            <ConversationContent className="max-w-3xl mx-auto px-6 py-6">
              {messages.length === 0 && (
                <ConversationEmptyState
                  title="Upload an image or ask about something visual"
                  description="Click the paperclip icon below to attach an image. The agent will describe what it sees."
                />
              )}

              {messages.map((message) => (
                <Message key={message.id} from={message.role}>
                  <MessageContent>
                    {/* Render user file attachments first */}
                    {message.role === "user" &&
                      message.parts.map((part, index) => {
                        if (part.type === "file" && "url" in part) {
                          const url = part.url as string;
                          if (url.startsWith("data:image")) {
                            return (
                              <img
                                key={`${message.id}-file-${index}`}
                                src={url}
                                alt={part.filename || "attachment"}
                                className="h-auto max-w-full max-h-80 rounded-md border border-border/60 mb-2"
                              />
                            );
                          }
                        }
                        return null;
                      })}

                    {message.parts.map((part, index) => {
                      if (part.type === "text") {
                        return (
                          <MessageResponse key={`${message.id}-text-${index}`}>
                            {part.text}
                          </MessageResponse>
                        );
                      }
                      return null;
                    })}
                  </MessageContent>
                </Message>
              ))}

              {/* Suggestions after first assistant response */}
              {messages.length > 0 &&
                messages[messages.length - 1].role === "assistant" &&
                status === "ready" && (
                  <Suggestions>
                    {SUGGESTIONS.map((s) => (
                      <Suggestion key={s} suggestion={s} onClick={send} />
                    ))}
                  </Suggestions>
                )}

              {error && (
                <div className="rounded-md border border-destructive bg-destructive/10 p-3 text-sm text-destructive">
                  Error: {error.message}
                </div>
              )}
            </ConversationContent>
          </Conversation>
        </div>

        <div className="border-t border-border/60 p-4">
          <div className="max-w-3xl mx-auto">
            {/* Attachment previews */}
            {attachments.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-3">
                {attachments.map((a) => (
                  <div
                    key={a.id}
                    className="relative group rounded-md border border-border/60 overflow-hidden"
                  >
                    <img
                      src={a.url}
                      alt={a.name}
                      className="h-20 w-20 object-cover"
                    />
                    <button
                      onClick={() => removeAttachment(a.id)}
                      className="absolute top-1 right-1 bg-black/70 text-white rounded-full p-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            <PromptInput onSubmit={handleSubmit}>
              <PromptInputTextarea placeholder="Ask a question about the image..." />
              <PromptInputTools>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  multiple
                  hidden
                  onChange={(e) => {
                    addFiles(e.target.files);
                    e.target.value = "";
                  }}
                />
                <PromptInputButton
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <Paperclip className="w-4 h-4" />
                </PromptInputButton>
              </PromptInputTools>
              <PromptInputSubmit status={status} />
            </PromptInput>
          </div>
        </div>
      </div>
    </DemoShell>
  );
}
