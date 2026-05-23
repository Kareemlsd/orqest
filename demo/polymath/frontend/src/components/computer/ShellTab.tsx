"use client";

/**
 * ShellTab — live feed of `shell.stdout` / `shell.stderr` / `tool.shell.*`
 * events for the current session. Phase 2 renders a monospaced scrolling
 * buffer. Phase 3 upgrades to xterm.js wired to a real PTY via noVNC.
 */
import { useEffect, useRef, useState } from "react";

import { useSidecar } from "@/hooks/useSidecar";
import type { AgentEvent } from "@/lib/events";

interface ShellLine {
  kind: "cmd" | "stdout" | "stderr" | "exit";
  text: string;
  ts: number;
}

export function ShellTab({ sessionId }: { sessionId: string }) {
  const [lines, setLines] = useState<ShellLine[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  useSidecar(sessionId, (evt) => {
    const line = toShellLine(evt);
    if (line) setLines((prev) => [...prev.slice(-500), line]);
  });

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines.length]);

  if (lines.length === 0) {
    return (
      <div className="flex flex-col items-start px-6 pt-[20vh]">
        <h2 className="font-serif text-[24px] text-foreground leading-tight">
          Shell
        </h2>
        <p className="mt-2 font-mono text-[11px] text-muted-foreground">
          Ask Polymath to run a command. stdout streams here.
        </p>
      </div>
    );
  }
  return (
    <div
      ref={scrollRef}
      className="h-full overflow-y-auto bg-surface-code px-4 py-3 font-mono text-[12px] leading-relaxed text-neutral-200"
    >
      {lines.map((line, i) => (
        <div key={i} className={colorFor(line.kind)}>
          {line.kind === "cmd" ? <span className="text-accent">$ </span> : null}
          {line.text}
        </div>
      ))}
    </div>
  );
}

function toShellLine(evt: AgentEvent): ShellLine | null {
  const data = evt.data as {
    command?: string;
    text?: string;
    exit_code?: number;
  };
  if (evt.event_type === "tool.shell.run_command.started" && data.command) {
    return { kind: "cmd", text: data.command, ts: Date.now() };
  }
  if (evt.event_type === "tool.python.run_snippet.started") {
    return { kind: "cmd", text: "python3 -c <snippet>", ts: Date.now() };
  }
  if (evt.event_type === "shell.stdout" && data.text) {
    return { kind: "stdout", text: data.text.trimEnd(), ts: Date.now() };
  }
  if (evt.event_type === "shell.stderr" && data.text) {
    return { kind: "stderr", text: data.text.trimEnd(), ts: Date.now() };
  }
  if (
    (evt.event_type === "tool.shell.run_command.completed" ||
      evt.event_type === "tool.python.run_snippet.completed") &&
    data.exit_code !== undefined
  ) {
    return { kind: "exit", text: `exit ${data.exit_code}`, ts: Date.now() };
  }
  return null;
}

function colorFor(kind: ShellLine["kind"]): string {
  switch (kind) {
    case "cmd":
      return "text-foreground";
    case "stdout":
      return "text-neutral-200 whitespace-pre-wrap";
    case "stderr":
      return "text-destructive whitespace-pre-wrap";
    case "exit":
      return "text-muted-foreground mt-1";
  }
}
