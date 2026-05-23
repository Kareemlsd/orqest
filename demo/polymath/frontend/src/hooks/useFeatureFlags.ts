"use client";

/**
 * useFeatureFlags — fetches the backend's client-visible feature flags
 * once on mount and caches them in module scope.
 *
 * The flags currently surfaced:
 *   - `browser`  : whether the noVNC `BrowserTab` should render
 *   - `healing`  : whether the healing subsystem is wired (informational;
 *                  the frontend currently doesn't gate UI on this)
 *
 * Backend endpoint: `GET /config` → `{ features: { browser, healing } }`.
 *
 * Default flags (used on initial render before the fetch resolves and
 * as a graceful fallback when the endpoint is unreachable) are set
 * conservatively to *not* render heavy UI surfaces — the user opts
 * IN by setting the corresponding env var on the backend.
 */
import { useEffect, useState } from "react";

import { backendBase } from "@/lib/api";

export interface FeatureFlags {
  browser: boolean;
  healing: boolean;
  sandboxed_html: boolean;
}

const DEFAULT_FLAGS: FeatureFlags = {
  browser: false,
  healing: true,
  sandboxed_html: true,
};

let _cached: FeatureFlags | null = null;

export function useFeatureFlags(): FeatureFlags {
  const [flags, setFlags] = useState<FeatureFlags>(() => _cached ?? DEFAULT_FLAGS);

  useEffect(() => {
    if (_cached !== null) return;
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(`${backendBase()}/config`);
        if (!resp.ok) return;
        const payload = (await resp.json()) as {
          features?: Partial<FeatureFlags>;
        };
        const merged: FeatureFlags = {
          ...DEFAULT_FLAGS,
          ...(payload.features ?? {}),
        };
        _cached = merged;
        if (!cancelled) setFlags(merged);
      } catch {
        // Network error / offline — keep defaults; nothing else to do.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return flags;
}
