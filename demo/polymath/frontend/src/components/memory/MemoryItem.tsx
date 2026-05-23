"use client";

/**
 * MemoryItem — a single row in the memory browser list.
 *
 * Visually a four-zone composition: a thin vertical rail in the kind
 * colour (saturated when the memory was used in the current turn,
 * muted otherwise); a serif title (italicised for episodic kind so
 * past events read like remembered events); an optional amber
 * `recalled · turn N` pill; the body in sans; and a row of mono meta
 * entries underneath (date written, recall count, similarity).
 */
import { cn } from "@/lib/utils";

export type MemoryItemKind = "semantic" | "episodic" | "procedural";

interface MemoryItemProps {
  kind: MemoryItemKind;
  title: string;
  body: React.ReactNode;
  meta: ReadonlyArray<string>;
  /** True when this entry was recalled in the current turn. */
  used?: boolean;
  /** Optional turn number for the "recalled · turn N" pill. */
  recalledTurn?: number;
}

export function MemoryItem({
  kind,
  title,
  body,
  meta,
  used = false,
  recalledTurn,
}: MemoryItemProps) {
  const colour = kindColour(kind);
  const railStyle = used
    ? { background: colour }
    : { background: kindMutedBackground(kind) };
  return (
    <div className="flex gap-3.5 py-3 border-b border-border-subtle last:border-b-0">
      <div
        className="w-1 self-stretch shrink-0 rounded-[1px]"
        style={railStyle}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-2 mb-1 flex-wrap">
          <span
            className={cn(
              "font-serif text-foreground",
              kind === "episodic" && "italic",
            )}
            style={{ fontSize: 13.5, letterSpacing: "-0.005em" }}
          >
            {title}
          </span>
          {used && recalledTurn !== undefined && (
            <span
              className="inline-flex items-center font-mono uppercase tracking-[0.04em]"
              style={{
                color: "var(--color-accent)",
                border: "1px solid var(--color-accent-subtle)",
                background: "var(--color-accent-subtle)",
                fontSize: 10,
                padding: "1px 6px",
                borderRadius: 3,
                height: 18,
                lineHeight: 1,
              }}
            >
              recalled · turn {String(recalledTurn).padStart(2, "0")}
            </span>
          )}
        </div>
        <div
          className="text-muted-foreground"
          style={{ fontSize: 12.5, lineHeight: 1.55 }}
        >
          {body}
        </div>
        <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5">
          {meta.map((m, i) => (
            <span
              key={i}
              className="font-mono uppercase text-muted-foreground/80 tracking-[0.04em]"
              style={{ fontSize: 10 }}
            >
              {m}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function kindColour(kind: MemoryItemKind): string {
  switch (kind) {
    case "semantic": return "var(--color-kind-semantic)";
    case "episodic": return "var(--color-kind-episodic)";
    case "procedural": return "var(--color-kind-procedural)";
  }
}

/** Muted hue for the rail when the entry isn't currently used. */
function kindMutedBackground(kind: MemoryItemKind): string {
  switch (kind) {
    case "semantic": return "oklch(0.78 0.06 220 / 0.35)";
    case "episodic": return "oklch(0.72 0.10 290 / 0.35)";
    case "procedural": return "oklch(0.78 0.10 150 / 0.35)";
  }
}
