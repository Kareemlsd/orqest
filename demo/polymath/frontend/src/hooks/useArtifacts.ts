"use client";

/**
 * useArtifacts — keeps the session's artifact list in sync.
 *
 * On mount: GET /sessions/{sid}/artifacts.
 * On any `artifact.created` event: prepend the artifact.
 */
import { useCallback, useEffect, useState } from "react";

import { backendBase } from "@/lib/api";
import type { Artifact } from "@/lib/events";
import { useSidecar } from "./useSidecar";

interface ArtifactRow {
  id: string;
  kind: string;
  mime: string;
  label: string;
  path: string;
  size_bytes: number;
  created_at: string;
}

export function useArtifacts(sessionId: string): { artifacts: Artifact[] } {
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);

  const refresh = useCallback(async () => {
    try {
      const resp = await fetch(`${backendBase()}/sessions/${sessionId}/artifacts`);
      if (!resp.ok) return;
      const data = (await resp.json()) as { artifacts: ArtifactRow[] };
      setArtifacts(
        data.artifacts.map((a) => ({
          id: a.id,
          kind: a.kind,
          mime: a.mime,
          label: a.label,
          path: a.path,
          created_at: a.created_at,
        })),
      );
    } catch {
      /* swallow */
    }
  }, [sessionId]);

  useEffect(() => {
    if (sessionId) refresh();
  }, [refresh, sessionId]);

  useSidecar(sessionId, (evt) => {
    if (evt.event_type === "artifact.created") {
      const data = evt.data as {
        id?: string;
        kind?: string;
        mime?: string;
        label?: string;
        path?: string;
      };
      if (!data.id) return;
      setArtifacts((prev) => {
        if (prev.some((a) => a.id === data.id)) return prev;
        return [
          {
            id: data.id!,
            kind: data.kind || "file",
            mime: data.mime || "application/octet-stream",
            label: data.label || "",
            path: data.path || "",
            created_at: new Date().toISOString(),
          },
          ...prev,
        ];
      });
    }
  });

  return { artifacts };
}
