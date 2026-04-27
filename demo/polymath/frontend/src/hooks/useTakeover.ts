"use client";

/**
 * useTakeover — tracks the session's takeover flag and exposes
 * `take` / `release` actions. Subscribes to `takeover.activated` and
 * `takeover.released` so multi-tab views stay coherent.
 */
import { useCallback, useEffect, useState } from "react";

import { backendBase } from "@/lib/api";
import { useSidecar } from "./useSidecar";

export function useTakeover(sessionId: string) {
  const [active, setActive] = useState(false);
  const [pending, setPending] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const resp = await fetch(`${backendBase()}/sessions/${sessionId}/takeover`);
      if (!resp.ok) return;
      const data = (await resp.json()) as { active: boolean };
      setActive(data.active);
    } catch {
      /* swallow */
    }
  }, [sessionId]);

  useEffect(() => {
    if (sessionId) refresh();
  }, [refresh, sessionId]);

  useSidecar(sessionId, (evt) => {
    if (evt.event_type === "takeover.activated") setActive(true);
    else if (evt.event_type === "takeover.released") setActive(false);
  });

  const take = useCallback(async () => {
    setPending(true);
    try {
      await fetch(`${backendBase()}/sessions/${sessionId}/takeover`, {
        method: "POST",
      });
    } finally {
      setPending(false);
    }
  }, [sessionId]);

  const release = useCallback(async () => {
    setPending(true);
    try {
      await fetch(`${backendBase()}/sessions/${sessionId}/resume`, {
        method: "POST",
      });
    } finally {
      setPending(false);
    }
  }, [sessionId]);

  return { active, pending, take, release };
}
