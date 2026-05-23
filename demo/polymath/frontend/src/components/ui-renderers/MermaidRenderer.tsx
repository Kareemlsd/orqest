"use client";

/**
 * MermaidRenderer — Layer 2 renderer for Mermaid diagrams (flowchart,
 * sequence, gantt, class, state, ER, etc.).
 *
 * Backend contract (`MermaidComponentData`):
 *   { diagram: string, title?: string }
 *
 * Security:
 *   - `securityLevel: "strict"` strips inline HTML and disables `<script>`
 *     blocks. Mermaid does its own sanitization on top.
 *   - The rendered SVG is injected via `dangerouslySetInnerHTML` because
 *     mermaid returns an SVG string. This is safe because mermaid has
 *     already sanitized — it does not preserve untrusted HTML.
 *
 * Rendering strategy:
 *   - We render asynchronously into local state and swap the markup once
 *     ready. While pending we show a `<Skeleton>`. On parse errors mermaid
 *     rejects the promise; we surface that via `<ErrorBox>`.
 *
 * Note on initialization:
 *   - `mermaid.initialize` is module-load side effect. That's the canonical
 *     usage; calling it on every render is wasteful. The "neutral" theme
 *     plays well with both light and dark canvas backgrounds.
 */
import { useEffect, useState } from "react";
import mermaid from "mermaid";

import { registerRenderer, type UIRenderer } from "./registry";
import { ErrorBox, Skeleton } from "./_helpers";

mermaid.initialize({
  startOnLoad: false,
  theme: "neutral",
  securityLevel: "strict",
});

interface MermaidData {
  diagram: string;
  title?: string;
}

const MermaidRenderer: UIRenderer<MermaidData> = (spec) => {
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Mermaid requires DOM-safe ids — strip non-alphanumerics and prefix.
  const id = `mermaid-${spec.component_id.replace(/[^a-zA-Z0-9_-]/g, "_")}`;

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setSvg(null);
    mermaid
      .render(id, spec.data.diagram)
      .then(
        ({ svg: rendered }) => {
          if (!cancelled) setSvg(rendered);
        },
        (err: unknown) => {
          if (!cancelled) {
            setError(err instanceof Error ? err.message : String(err));
          }
        },
      );
    return () => {
      cancelled = true;
    };
  }, [spec.data.diagram, id]);

  if (error) return <ErrorBox message={`Mermaid render failed: ${error}`} />;
  if (!svg) return <Skeleton />;

  return (
    <div className="w-full overflow-auto">
      {spec.data.title && (
        <div className="font-mono text-[11px] text-muted-foreground mb-1">
          {spec.data.title}
        </div>
      )}
      <div dangerouslySetInnerHTML={{ __html: svg }} />
    </div>
  );
};

registerRenderer("mermaid", MermaidRenderer);
export default MermaidRenderer;
