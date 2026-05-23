"use client";

/**
 * UIComponentRenderer — recursive dispatcher for typed UI component
 * specs. Looks up a renderer for `spec.component_type` and invokes it
 * with a `RenderContext` that contains the session id, a recursive
 * `render` callback (so layout-style renderers can dispatch on their
 * children), and a backend `emitEvent` POST helper.
 *
 * Unknown component types fall through to a debug `<FallbackRenderer>`
 * so the dispatcher is forward-compatible — a third-party component
 * type appears as a JSON dump rather than a hard error.
 *
 * The `./register-all` side-effect import primes the registry with
 * every Layer 1/2/3 renderer module. Only this file imports the barrel,
 * so consumers of `<UIComponentRenderer>` don't need to remember to do
 * it themselves.
 */
import { useCallback } from "react";

import { backendBase } from "@/lib/api";

import {
  type RenderContext,
  type UIComponentSpec,
  getRenderer,
} from "./registry";
import "./register-all";

interface UIComponentRendererProps {
  spec: UIComponentSpec;
  sessionId: string;
}

export function UIComponentRenderer({ spec, sessionId }: UIComponentRendererProps) {
  const emitEvent = useCallback(
    async (eventName: string, payload: Record<string, unknown>) => {
      try {
        await fetch(`${backendBase()}/sessions/${sessionId}/ui/event`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            event_name: eventName,
            component_id: spec.component_id,
            payload,
          }),
        });
      } catch (err) {
        console.warn("UI event POST failed", err);
      }
    },
    [sessionId, spec.component_id],
  );

  const context: RenderContext = {
    sessionId,
    render: (childSpec) => (
      <UIComponentRenderer spec={childSpec} sessionId={sessionId} />
    ),
    emitEvent,
  };

  const renderer = getRenderer(spec.component_type);
  if (!renderer) {
    return <FallbackRenderer spec={spec} />;
  }
  return <>{renderer(spec, context)}</>;
}

function FallbackRenderer({ spec }: { spec: UIComponentSpec }) {
  return (
    <div className="border border-dashed border-border-default rounded-md p-3 my-2 bg-surface-elevated/50">
      <div className="font-mono text-[10px] text-muted-foreground mb-1">
        Unknown component_type: {spec.component_type}
      </div>
      <pre className="font-mono text-[10px] text-foreground whitespace-pre-wrap break-words">
        {JSON.stringify(spec.data, null, 2)}
      </pre>
    </div>
  );
}
