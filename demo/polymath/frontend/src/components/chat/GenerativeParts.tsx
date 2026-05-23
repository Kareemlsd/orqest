"use client";

/**
 * Inline generative UI parts — chart / file / table cards rendered inside
 * the assistant message stream.
 *
 * Phase 0: stub. Renders a label so the component import path is real
 * and Phase 4 can wire real artifact thumbnails without restructuring.
 */
interface GenerativePartProps {
  kind: "chart" | "file" | "table" | string;
  label: string;
}

export function GenerativePart({ kind, label }: GenerativePartProps) {
  return (
    <div className="my-2 rounded-md border border-border-subtle bg-surface-card px-3 py-2 text-[11px] font-mono text-muted-foreground">
      <span className="text-foreground">{kind}</span>
      <span className="mx-1.5">·</span>
      {label}
    </div>
  );
}
