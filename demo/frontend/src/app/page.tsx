"use client";

import { useChat } from "@ai-sdk/react";

export default function Home() {
  const { messages, input, handleInputChange, handleSubmit, isLoading, error } =
    useChat({
      api: "http://localhost:8000/api/chat",
    });

  return (
    <main className="flex flex-col h-screen bg-neutral-950 text-neutral-100">
      {/* Header */}
      <header className="border-b border-neutral-800 px-6 py-4">
        <div className="max-w-3xl mx-auto flex items-center gap-3">
          <div className="w-8 h-8 rounded bg-teal-700 flex items-center justify-center text-sm font-bold">
            O
          </div>
          <div>
            <h1 className="text-lg font-semibold tracking-tight">
              Orqest Demo
            </h1>
            <p className="text-xs text-neutral-500">
              Streaming agent chat via Vercel AI SDK + pydantic-ai
            </p>
          </div>
        </div>
      </header>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-6 py-6 space-y-6">
          {messages.length === 0 && (
            <div className="text-center py-20">
              <p className="text-neutral-500 text-sm">
                Ask the Orqest research assistant anything.
              </p>
              <p className="text-neutral-600 text-xs mt-2">
                It has tools for time, topic analysis, and calculations.
              </p>
            </div>
          )}

          {messages.map((m) => (
            <div key={m.id} className="flex gap-3">
              {/* Avatar */}
              <div
                className={`w-7 h-7 rounded flex-shrink-0 flex items-center justify-center text-xs font-medium ${
                  m.role === "user"
                    ? "bg-neutral-800 text-neutral-300"
                    : "bg-teal-800 text-teal-200"
                }`}
              >
                {m.role === "user" ? "U" : "O"}
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0">
                <p className="text-xs text-neutral-500 mb-1">
                  {m.role === "user" ? "You" : "Orqest Agent"}
                </p>

                {/* Text content */}
                {m.content && (
                  <div className="text-sm leading-relaxed whitespace-pre-wrap text-neutral-200">
                    {m.content}
                  </div>
                )}

                {/* Tool calls */}
                {m.toolInvocations?.map((tool) => (
                  <div
                    key={tool.toolCallId}
                    className="mt-2 border border-neutral-800 rounded p-3 bg-neutral-900"
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs font-mono text-teal-500">
                        tool:{tool.toolName}
                      </span>
                      <span
                        className={`text-xs px-1.5 py-0.5 rounded ${
                          tool.state === "result"
                            ? "bg-green-900/30 text-green-400"
                            : "bg-yellow-900/30 text-yellow-400"
                        }`}
                      >
                        {tool.state === "result" ? "done" : "running..."}
                      </span>
                    </div>

                    {/* Tool args */}
                    {tool.args && Object.keys(tool.args).length > 0 && (
                      <pre className="text-xs text-neutral-400 font-mono mt-1">
                        {JSON.stringify(tool.args, null, 2)}
                      </pre>
                    )}

                    {/* Tool result */}
                    {tool.state === "result" && tool.result && (
                      <pre className="text-xs text-neutral-300 font-mono mt-2 border-t border-neutral-800 pt-2 whitespace-pre-wrap">
                        {typeof tool.result === "string"
                          ? tool.result
                          : JSON.stringify(tool.result, null, 2)}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}

          {/* Loading indicator */}
          {isLoading && (
            <div className="flex gap-3">
              <div className="w-7 h-7 rounded bg-teal-800 flex-shrink-0 flex items-center justify-center">
                <div className="w-2 h-2 rounded-full bg-teal-400 animate-pulse" />
              </div>
              <p className="text-sm text-neutral-500 self-center">
                Agent is thinking...
              </p>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="border border-red-800/50 rounded p-3 bg-red-950/30 text-red-300 text-sm">
              Error: {error.message}
            </div>
          )}
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-neutral-800 px-6 py-4">
        <form
          onSubmit={handleSubmit}
          className="max-w-3xl mx-auto flex gap-3"
        >
          <input
            value={input}
            onChange={handleInputChange}
            placeholder="Ask anything... (try: &apos;What time is it?&apos; or &apos;Analyze quantum computing&apos;)"
            className="flex-1 bg-neutral-900 border border-neutral-700 rounded-lg px-4 py-2.5 text-sm text-neutral-100 placeholder:text-neutral-600 focus:outline-none focus:border-teal-700 focus:ring-1 focus:ring-teal-700"
          />
          <button
            type="submit"
            disabled={isLoading || !input.trim()}
            className="bg-teal-700 hover:bg-teal-600 disabled:bg-neutral-800 disabled:text-neutral-600 text-white px-5 py-2.5 rounded-lg text-sm font-medium transition-colors"
          >
            Send
          </button>
        </form>
      </div>
    </main>
  );
}
