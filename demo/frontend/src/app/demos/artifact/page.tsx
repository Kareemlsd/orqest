"use client";

import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { useMemo, useState } from "react";
import { Code2, Eye } from "lucide-react";
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
import {
  Artifact,
  ArtifactContent,
  ArtifactDescription,
  ArtifactHeader,
  ArtifactTitle,
} from "@/components/ai-elements/artifact";
import { CodeBlock } from "@/components/ai-elements/code-block";
import { DemoShell } from "@/components/demo-shell";

type ArtifactKind = "html" | "svg" | "jsx" | "python";

type ExtractedArtifact = {
  language: ArtifactKind;
  code: string;
};

/** Extract the last fenced code block from a string, returning its language + content. */
function extractArtifact(text: string): ExtractedArtifact | null {
  const re = /```(html|svg|jsx|python)\s*\n([\s\S]*?)```/gi;
  let match: RegExpExecArray | null;
  let last: ExtractedArtifact | null = null;
  while ((match = re.exec(text)) !== null) {
    last = {
      language: match[1].toLowerCase() as ArtifactKind,
      code: match[2].trim(),
    };
  }
  return last;
}

function ArtifactPreview({ artifact }: { artifact: ExtractedArtifact }) {
  if (artifact.language === "svg") {
    return (
      <div
        className="w-full h-full flex items-center justify-center p-8 bg-white"
        dangerouslySetInnerHTML={{ __html: artifact.code }}
      />
    );
  }

  if (artifact.language === "html") {
    return (
      <iframe
        srcDoc={artifact.code}
        className="w-full h-full bg-white"
        sandbox="allow-scripts"
        title="HTML Preview"
      />
    );
  }

  if (artifact.language === "jsx") {
    // JSX: wrap in a minimal HTML shell with React from CDN
    const html = `
<!DOCTYPE html>
<html>
<head>
<script src="https://unpkg.com/react@19/umd/react.development.js"></script>
<script src="https://unpkg.com/react-dom@19/umd/react-dom.development.js"></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
<style>
body { margin: 0; font-family: system-ui, sans-serif; padding: 1.5rem; }
</style>
</head>
<body>
<div id="root"></div>
<script type="text/babel">
${artifact.code}
const __Component = typeof Component !== 'undefined' ? Component :
  typeof App !== 'undefined' ? App :
  typeof Main !== 'undefined' ? Main :
  (() => React.createElement('pre', null, 'No exported component found. Name your component App, Component, or Main.'));
ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(__Component));
</script>
</body>
</html>`;
    return (
      <iframe
        srcDoc={html}
        className="w-full h-full bg-white"
        sandbox="allow-scripts"
        title="React Preview"
      />
    );
  }

  // python — no preview, just show code
  return (
    <div className="p-6 text-sm text-muted-foreground flex items-center justify-center h-full">
      Python code has no visual preview.
    </div>
  );
}

export default function ArtifactStudio() {
  const { messages, sendMessage, status, error } = useChat({
    transport: new DefaultChatTransport({ api: "/api/demos/artifact/chat" }),
  });
  const [tab, setTab] = useState<"code" | "preview">("preview");

  const currentArtifact = useMemo<ExtractedArtifact | null>(() => {
    // Walk messages backwards, take the last assistant message's extracted artifact
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m.role !== "assistant") continue;
      const text = m.parts
        .filter((p) => p.type === "text")
        .map((p) => ("text" in p ? p.text : ""))
        .join("\n");
      const extracted = extractArtifact(text);
      if (extracted) return extracted;
    }
    return null;
  }, [messages]);

  const handleSubmit = (message: { text?: string }) => {
    const text = message.text?.trim();
    if (!text) return;
    sendMessage({ text });
  };

  return (
    <DemoShell
      title="Artifact Studio"
      subtitle="Dual-pane code generation with live preview — Claude-style"
    >
      <div className="flex h-full">
        {/* Left: chat */}
        <div className="flex-1 flex flex-col border-r border-border/60">
          <div className="flex-1 overflow-hidden">
            <Conversation className="h-full">
              <ConversationContent className="px-6 py-6">
                {messages.length === 0 && (
                  <ConversationEmptyState
                    title="Generate something visual"
                    description='Try: "An SVG of a sunset over mountains" · "A React counter component" · "A pricing card in HTML"'
                  />
                )}

                {messages.map((message) => (
                  <Message key={message.id} from={message.role}>
                    <MessageContent>
                      {message.parts.map((part, index) => {
                        if (part.type === "text") {
                          // Strip the code block from the visible message —
                          // it's shown in the artifact panel.
                          const stripped = part.text.replace(
                            /```(html|svg|jsx|python)\s*\n[\s\S]*?```/gi,
                            "_[artifact rendered on the right →]_"
                          );
                          return (
                            <MessageResponse key={`${message.id}-text-${index}`}>
                              {stripped}
                            </MessageResponse>
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
              <PromptInputTextarea placeholder="Describe what to build — HTML, SVG, or React component..." />
              <PromptInputSubmit status={status} />
            </PromptInput>
          </div>
        </div>

        {/* Right: artifact panel */}
        <div className="w-[520px] flex flex-col bg-background">
          {currentArtifact ? (
            <Artifact className="flex-1 border-0 rounded-none flex flex-col">
              <ArtifactHeader className="border-b border-border/60">
                <div className="flex-1">
                  <ArtifactTitle>
                    Artifact ({currentArtifact.language.toUpperCase()})
                  </ArtifactTitle>
                  <ArtifactDescription>
                    Generated by the agent
                  </ArtifactDescription>
                </div>
                <div className="flex gap-1">
                  <button
                    onClick={() => setTab("preview")}
                    className={`flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md transition-colors ${
                      tab === "preview"
                        ? "bg-accent text-accent-foreground"
                        : "text-muted-foreground hover:bg-accent/50"
                    }`}
                  >
                    <Eye className="w-3 h-3" />
                    Preview
                  </button>
                  <button
                    onClick={() => setTab("code")}
                    className={`flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md transition-colors ${
                      tab === "code"
                        ? "bg-accent text-accent-foreground"
                        : "text-muted-foreground hover:bg-accent/50"
                    }`}
                  >
                    <Code2 className="w-3 h-3" />
                    Code
                  </button>
                </div>
              </ArtifactHeader>
              <ArtifactContent className="flex-1 overflow-hidden p-0">
                {tab === "preview" ? (
                  <ArtifactPreview artifact={currentArtifact} />
                ) : (
                  <div className="h-full overflow-auto p-4">
                    <CodeBlock
                      code={currentArtifact.code}
                      language={
                        // Shiki's default bundle doesn't include "svg" —
                        // render it as XML which handles SVG identically.
                        currentArtifact.language === "svg"
                          ? "xml"
                          : currentArtifact.language
                      }
                    />
                  </div>
                )}
              </ArtifactContent>
            </Artifact>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
              <div className="w-12 h-12 rounded-md border border-border/60 flex items-center justify-center mb-4 text-muted-foreground">
                <Code2 className="w-5 h-5" />
              </div>
              <p className="text-sm font-medium">Artifact panel</p>
              <p className="text-xs text-muted-foreground mt-1 max-w-xs">
                Generated code will appear here with a live preview. Ask the
                agent to build something.
              </p>
            </div>
          )}
        </div>
      </div>
    </DemoShell>
  );
}
