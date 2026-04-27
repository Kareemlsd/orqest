"use client";

/**
 * FilesTab — browsable tree of the session's /workspace via
 * `GET /sessions/{sid}/files?path=…`. Auto-refreshes on any
 * `tool.fs.*.completed` event.
 */
import { useCallback, useEffect, useState } from "react";

import { backendBase } from "@/lib/api";
import { useSidecar } from "@/hooks/useSidecar";

interface Entry {
  name: string;
  path: string;
  kind: "file" | "dir";
  size: number;
}

const FS_REFRESH_EVENTS = new Set([
  "tool.fs.write_file.completed",
  "tool.fs.edit_file.completed",
  "tool.shell.run_command.completed",
  "tool.python.run_snippet.completed",
  "artifact.created",
]);

export function FilesTab({ sessionId }: { sessionId: string }) {
  const [cwd, setCwd] = useState<string>("");
  const [entries, setEntries] = useState<Entry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [preview, setPreview] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const resp = await fetch(
        `${backendBase()}/sessions/${sessionId}/files?path=${encodeURIComponent(cwd)}`,
      );
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({ detail: "error" }));
        setError(body.detail || `HTTP ${resp.status}`);
        setEntries([]);
        return;
      }
      const data = (await resp.json()) as { entries: Entry[] };
      setEntries(data.entries);
      setError(null);
    } catch (e) {
      setError(String(e));
      setEntries([]);
    }
  }, [sessionId, cwd]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useSidecar(sessionId, (evt) => {
    if (FS_REFRESH_EVENTS.has(evt.event_type)) refresh();
  });

  const openFile = async (path: string) => {
    setSelected(path);
    setPreview(null);
    try {
      const resp = await fetch(
        `${backendBase()}/sessions/${sessionId}/files/read?path=${encodeURIComponent(path)}`,
      );
      if (!resp.ok) {
        setPreview(`error: ${resp.status}`);
        return;
      }
      const data = (await resp.json()) as { text?: string; binary?: boolean };
      setPreview(data.binary ? "<binary>" : (data.text ?? ""));
    } catch (e) {
      setPreview(String(e));
    }
  };

  return (
    <div className="h-full flex">
      <div className="w-64 border-r border-border-subtle overflow-y-auto">
        <div className="flex items-center gap-2 px-3 py-2 border-b border-border-subtle font-mono text-[11px] text-muted-foreground">
          <button
            disabled={!cwd}
            onClick={() =>
              setCwd(cwd.includes("/") ? cwd.slice(0, cwd.lastIndexOf("/")) : "")
            }
            className="disabled:opacity-40 hover:text-foreground"
          >
            ../
          </button>
          <span className="truncate">/{cwd || ""}</span>
        </div>
        {error ? (
          <div className="px-3 py-2 text-[11px] text-destructive font-mono">
            {error}
          </div>
        ) : null}
        <ul>
          {entries.map((e) => (
            <li
              key={e.path}
              className={`px-3 py-1 font-mono text-[12px] cursor-pointer hover:bg-surface-elevated ${
                selected === e.path ? "bg-surface-elevated" : ""
              }`}
              onClick={() => (e.kind === "dir" ? setCwd(e.path) : openFile(e.path))}
            >
              <span className="text-muted-foreground">
                {e.kind === "dir" ? "▸ " : "  "}
              </span>
              {e.name}
            </li>
          ))}
          {!entries.length && !error ? (
            <li className="px-3 py-2 font-mono text-[11px] text-muted-foreground">
              empty
            </li>
          ) : null}
        </ul>
      </div>
      <div className="flex-1 overflow-y-auto bg-surface-code">
        {preview !== null ? (
          <pre className="px-4 py-3 font-mono text-[12px] text-neutral-200 whitespace-pre-wrap break-words">
            {preview}
          </pre>
        ) : (
          <div className="flex flex-col items-start px-6 pt-[20vh]">
            <h2 className="font-serif text-[24px] text-foreground leading-tight">
              Files
            </h2>
            <p className="mt-2 font-mono text-[11px] text-muted-foreground">
              Click a file to preview.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
