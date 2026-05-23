"use client";

/**
 * ChartsTab — all chart components emitted on the typed `ui.chart.*`
 * channel for the session.
 *
 * Left rail lists chart components newest-first. Right pane shows the
 * selected chart at full width. PNG-backed charts (the only shape
 * currently emitted by `tools/report.py:_render_chart`) resolve via
 * `metadata.artifact_id` → `/sessions/{sid}/artifacts/{id}`.
 */
import { useEffect, useState } from "react";

import { backendBase } from "@/lib/api";
import { useUIComponents } from "@/hooks/useUIComponents";

interface ChartSeries {
  name: string;
  points: Record<string, unknown>[];
}

interface ChartData {
  chart_kind: string;
  title: string;
  x_axis: string | null;
  y_axis: string | null;
  series: ChartSeries[];
  config: Record<string, unknown>;
}

export function ChartsTab({ sessionId }: { sessionId: string }) {
  const { components } = useUIComponents<ChartData>(sessionId, "chart");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Auto-select newest on first arrival, and follow the head when new
  // charts arrive while nothing is selected.
  useEffect(() => {
    if (!selectedId && components.length > 0) {
      setSelectedId(components[0].component_id);
    }
  }, [components, selectedId]);

  if (components.length === 0) {
    return (
      <div className="flex flex-col items-start px-6 pt-[20vh]">
        <h2 className="font-serif text-[24px] text-foreground leading-tight">
          Charts
        </h2>
        <p className="mt-2 font-mono text-[11px] text-muted-foreground">
          Figures rendered by the agent show up here.
        </p>
      </div>
    );
  }

  const current =
    components.find((c) => c.component_id === selectedId) ?? components[0];
  const artifactId = current.metadata.artifact_id as string | undefined;
  const title = current.data.title || "";

  return (
    <div className="h-full flex">
      <div className="w-64 border-r border-border-subtle overflow-y-auto">
        <ul>
          {components.map((c) => (
            <li
              key={c.component_id}
              onClick={() => setSelectedId(c.component_id)}
              className={`px-3 py-2 cursor-pointer font-mono text-[12px] border-b border-border-subtle/60 hover:bg-surface-elevated ${
                c.component_id === selectedId ? "bg-surface-elevated" : ""
              }`}
            >
              <div className="text-foreground truncate">
                {c.data.title || c.component_id}
              </div>
              <div className="text-[10px] text-muted-foreground">
                {new Date(c.created_at).toLocaleTimeString()}
              </div>
            </li>
          ))}
        </ul>
      </div>
      <div className="flex-1 overflow-auto bg-surface-code flex items-center justify-center p-6">
        {artifactId ? (
          <img
            src={`${backendBase()}/sessions/${sessionId}/artifacts/${artifactId}`}
            alt={title}
            className="max-w-full max-h-full rounded border border-border-subtle"
          />
        ) : current.data.series.length > 0 ? (
          // ClientChart spec — wire when backend forwards structured plot
          // data per `tools/report.py` TODO. Today `_render_chart` produces
          // a binary PNG and leaves `series` empty; once it accepts
          // structured (x, y) points, render here via Plotly/Recharts.
          <div className="text-muted-foreground font-mono text-[11px]">
            Structured chart series not yet rendered client-side.
          </div>
        ) : null}
      </div>
    </div>
  );
}
