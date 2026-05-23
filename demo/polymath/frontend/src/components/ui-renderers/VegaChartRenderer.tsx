"use client";

/**
 * VegaChartRenderer — Layer 2 declarative-grammar renderer for Vega-Lite specs.
 *
 * Backend contract (`VegaChartComponentData`):
 *   { spec: object }   // an arbitrary Vega / Vega-Lite JSON spec
 *
 * Rendering strategy:
 *   - We use `vega-embed` (the canonical embed helper). It accepts both Vega
 *     and Vega-Lite specs and dispatches internally; we don't need to know
 *     which dialect the agent emitted.
 *   - All renders happen in a `useEffect` so the JSON spec is treated as
 *     state — the chart is finalized + re-mounted when the spec changes.
 *   - Malformed specs from the agent are caught and surfaced via `<ErrorBox>`
 *     so the dispatcher / parent canvas never goes blank.
 *
 * Bundle note: `vega-embed` pulls in vega + vega-lite + d3-* fragments.
 * That's ~700 KB minified. Acceptable for a desktop-class analytics surface;
 * if we ever ship a mobile bundle we'd split this behind a dynamic import.
 */
import { useEffect, useRef, useState } from "react";
import embed from "vega-embed";

import { registerRenderer, type UIRenderer } from "./registry";
import { ErrorBox } from "./_helpers";

interface VegaChartData {
  spec: object;
}

const VegaChartRenderer: UIRenderer<VegaChartData> = (spec) => {
  const ref = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    let view: { finalize?: () => void } | null = null;
    let cancelled = false;

    setError(null);
    embed(ref.current, spec.data.spec as Parameters<typeof embed>[1], {
      actions: false,
      renderer: "canvas",
    })
      .then((result) => {
        if (cancelled) {
          result.view.finalize?.();
          return;
        }
        view = result.view as { finalize?: () => void };
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });

    return () => {
      cancelled = true;
      try {
        view?.finalize?.();
      } catch {
        // best-effort cleanup; ignore
      }
    };
  }, [spec.data.spec]);

  return (
    <div className="w-full">
      {error ? (
        <ErrorBox message={`Vega render failed: ${error}`} />
      ) : (
        <div ref={ref} className="w-full overflow-auto" />
      )}
    </div>
  );
};

registerRenderer("vega_chart", VegaChartRenderer);
export default VegaChartRenderer;
