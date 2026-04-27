"use client";

/**
 * BrowserTab — live noVNC viewport of the session's sandbox Chromium.
 *
 * On mount, asks the backend for the session's `viewport_url` (which
 * ensures the sandbox is running and maps a host port to noVNC :6080).
 * Renders an iframe pointing at that URL. The Chromium inside the
 * sandbox runs under an Xvfb display; anything the agent does — open
 * URL, click, type — is mirrored here in real time.
 */
import { useEffect, useState } from "react";

import { backendBase } from "@/lib/api";
import { useTakeover } from "@/hooks/useTakeover";

export function BrowserTab({ sessionId }: { sessionId: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { active: takeoverActive } = useTakeover(sessionId);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(
          `${backendBase()}/sessions/${sessionId}/viewport_url`,
        );
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({ detail: "error" }));
          if (!cancelled) setError(body.detail || `HTTP ${resp.status}`);
          return;
        }
        const data = (await resp.json()) as { url: string };
        if (!cancelled) setUrl(data.url);
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
    // Re-fetch when takeover toggles so view_only flips.
  }, [sessionId, takeoverActive]);

  if (error) {
    return (
      <div className="flex flex-col items-start px-6 pt-[20vh]">
        <h2 className="font-serif text-[24px] text-foreground leading-tight">
          Browser
        </h2>
        <p className="mt-2 font-mono text-[11px] text-destructive">{error}</p>
      </div>
    );
  }

  if (!url) {
    return (
      <div className="flex flex-col items-start px-6 pt-[20vh]">
        <h2 className="font-serif text-[24px] text-foreground leading-tight">
          Browser
        </h2>
        <p className="mt-2 font-mono text-[11px] text-muted-foreground">
          Booting sandbox viewport…
        </p>
      </div>
    );
  }

  return (
    <iframe
      src={url}
      title="Polymath Browser"
      className="h-full w-full border-0 bg-black"
    />
  );
}
