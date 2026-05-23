"use client";

/**
 * EmptyWorkspaceState — editorial placeholder rendered behind the
 * dockview grid when no panels are open.
 *
 * The visual is a softly-grided background, a mono announcement,
 * a serif italic line of "what tabs are for", and a row of muted
 * pills naming the kinds of tabs that can appear (shell / files /
 * browser / memory / agents).
 *
 * Mounted as a transparent overlay inside DockviewWorkspace; the
 * pointer-events are disabled so the dockview drop targets behind it
 * still catch interactions normally.
 */
import { Brain, Files, Globe, Terminal, Users } from "lucide-react";

interface PillProps {
  icon: React.ReactNode;
  label: string;
}

function Pill({ icon, label }: PillProps) {
  return (
    <span
      className="inline-flex items-center gap-1.5 font-mono uppercase tracking-[0.04em] text-muted-foreground"
      style={{
        border: "1px solid var(--color-border-default)",
        background: "transparent",
        fontSize: 10,
        padding: "1px 7px 1px 6px",
        borderRadius: 3,
        height: 18,
        lineHeight: 1,
      }}
    >
      <span style={{ display: "inline-flex", color: "inherit" }} aria-hidden>
        {icon}
      </span>
      {label}
    </span>
  );
}

export function EmptyWorkspaceState() {
  return (
    <div
      className="absolute inset-0 flex items-center justify-center pointer-events-none"
      aria-hidden
    >
      {/* Light grid texture */}
      <div
        className="absolute inset-0"
        style={{
          backgroundImage:
            "linear-gradient(var(--color-border-subtle) 1px, transparent 1px), linear-gradient(90deg, var(--color-border-subtle) 1px, transparent 1px)",
          backgroundSize: "64px 64px",
          opacity: 0.4,
        }}
      />
      <div className="relative text-center px-8" style={{ maxWidth: 420 }}>
        <span
          className="font-mono uppercase tracking-[0.04em] text-muted-foreground"
          style={{ fontSize: 10 }}
        >
          workspace · awaiting task
        </span>
        <p
          className="font-serif italic text-muted-foreground mt-3.5"
          style={{
            fontSize: 22,
            lineHeight: 1.4,
            margin: "14px 0 0",
            letterSpacing: "-0.01em",
          }}
        >
          Tabs appear when I reach for tools. Each one is a window into what I&apos;m doing.
        </p>
        <div className="mt-6 flex justify-center gap-2 flex-wrap">
          <Pill icon={<Terminal size={9} />} label="shell" />
          <Pill icon={<Files size={9} />} label="files" />
          <Pill icon={<Globe size={9} />} label="browser" />
          <Pill icon={<Brain size={9} />} label="memory" />
          <Pill icon={<Users size={9} />} label="agents" />
        </div>
      </div>
    </div>
  );
}
