"use client";

/**
 * EditorTab — read-only Monaco viewer for the last file written or edited
 * by the agent. Phase 2 scope: preview only (no saves). Phase 5 will add
 * takeover-mode writes.
 */
import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";

import { backendBase } from "@/lib/api";
import { useSidecar } from "@/hooks/useSidecar";
import type { AgentEvent } from "@/lib/events";

// Monaco is ~200kB minified; lazy-load + disable SSR.
const Monaco = dynamic(() => import("@monaco-editor/react"), { ssr: false });

const LANG_BY_EXT: Record<string, string> = {
  py: "python",
  js: "javascript",
  ts: "typescript",
  tsx: "typescript",
  json: "json",
  md: "markdown",
  yml: "yaml",
  yaml: "yaml",
  sh: "shell",
  html: "html",
  css: "css",
  txt: "plaintext",
};

export function EditorTab({ sessionId }: { sessionId: string }) {
  const [path, setPath] = useState<string | null>(null);
  const [text, setText] = useState<string>("");

  const language = useMemo(() => {
    if (!path) return "plaintext";
    const ext = path.includes(".") ? path.split(".").pop()?.toLowerCase() : null;
    return (ext && LANG_BY_EXT[ext]) || "plaintext";
  }, [path]);

  useSidecar(sessionId, (evt: AgentEvent) => {
    const data = evt.data as { path?: string };
    if (
      (evt.event_type === "tool.fs.write_file.completed" ||
        evt.event_type === "tool.fs.edit_file.completed" ||
        evt.event_type === "tool.fs.read_file.completed") &&
      data.path
    ) {
      setPath(data.path);
    }
  });

  useEffect(() => {
    if (!path) return;
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(
          `${backendBase()}/sessions/${sessionId}/files/read?path=${encodeURIComponent(path)}`,
        );
        if (!resp.ok) return;
        const data = (await resp.json()) as { text?: string; binary?: boolean };
        if (!cancelled) setText(data.binary ? "<binary file>" : (data.text ?? ""));
      } catch {
        /* swallow */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, path]);

  if (!path) {
    return (
      <div className="flex flex-col items-start px-6 pt-[20vh]">
        <h2 className="font-serif text-[24px] text-foreground leading-tight">
          Editor
        </h2>
        <p className="mt-2 font-mono text-[11px] text-muted-foreground">
          The last file the agent touched opens here.
        </p>
      </div>
    );
  }
  return (
    <div className="h-full flex flex-col">
      <div className="border-b border-border-subtle px-3 py-1.5 font-mono text-[11px] text-muted-foreground">
        {path}
      </div>
      <div className="flex-1 min-h-0">
        <Monaco
          value={text}
          language={language}
          theme="vs-dark"
          options={{
            readOnly: true,
            minimap: { enabled: false },
            fontSize: 12,
            fontFamily: "var(--font-mono)",
            scrollBeyondLastLine: false,
            lineNumbers: "on",
            wordWrap: "on",
          }}
        />
      </div>
    </div>
  );
}
