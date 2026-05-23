"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { createSession } from "@/lib/api";

/**
 * Landing page — single call to action. POSTs /sessions, redirects to
 * the session shell. No chips, no marketing copy, no icons. Left-aligned
 * editorial layout (design-layout.md).
 */
export default function LandingPage() {
  const router = useRouter();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setStarting(true);
    setError(null);
    try {
      const session = await createSession();
      router.push(`/sessions/${session.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start session.");
      setStarting(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center px-12">
      <div className="max-w-2xl">
        <h1 className="font-serif text-5xl tracking-tight text-foreground">
          Polymath
        </h1>
        <p className="mt-4 text-muted-foreground text-[15px] leading-relaxed">
          General-purpose autonomous agent. Type a goal.
        </p>
        <button
          type="button"
          onClick={start}
          disabled={starting}
          className="mt-10 inline-flex items-center h-9 px-4 rounded-md border border-border-default bg-surface-elevated text-[13px] font-medium text-foreground transition-colors hover:border-accent disabled:opacity-50"
        >
          {starting ? "Starting..." : "Start a session"}
        </button>
        {error && (
          <p className="mt-4 text-[13px] text-destructive font-mono">{error}</p>
        )}
      </div>
    </main>
  );
}
