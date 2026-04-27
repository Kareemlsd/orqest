"use client";

/**
 * ReportTab — renders the most recent `kind="report"` artifact as a PDF.
 *
 * Falls back to an iframe pointing at the backend's artifact-download URL
 * (the backend serves the PDF with its native mime type, browsers handle
 * the rest). An iframe keeps the initial bundle small and sidesteps
 * worker-path issues that plague react-pdf in Next 16 app-router builds.
 */
import { useMemo } from "react";

import { backendBase } from "@/lib/api";
import { useArtifacts } from "@/hooks/useArtifacts";

export function ReportTab({ sessionId }: { sessionId: string }) {
  const { artifacts } = useArtifacts(sessionId);
  const latest = useMemo(
    () =>
      artifacts.find((a) => a.kind === "report" || a.mime === "application/pdf"),
    [artifacts],
  );

  if (!latest) {
    return (
      <div className="flex flex-col items-start px-6 pt-[20vh]">
        <h2 className="font-serif text-[24px] text-foreground leading-tight">
          Report
        </h2>
        <p className="mt-2 font-mono text-[11px] text-muted-foreground">
          PDF reports appear here.
        </p>
      </div>
    );
  }

  const src = `${backendBase()}/sessions/${sessionId}/artifacts/${latest.id}`;
  return (
    <div className="h-full flex flex-col">
      <div className="border-b border-border-subtle px-3 py-1.5 font-mono text-[11px] text-muted-foreground flex items-center justify-between">
        <span className="truncate">{latest.label || latest.path}</span>
        <a
          href={src}
          download
          className="text-accent hover:text-accent-hover transition-colors"
        >
          download
        </a>
      </div>
      <iframe
        src={src}
        title={latest.label || "Report"}
        className="flex-1 min-h-0 border-0 bg-surface-code"
      />
    </div>
  );
}
