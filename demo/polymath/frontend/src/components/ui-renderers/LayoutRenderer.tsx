"use client";

/**
 * LayoutRenderer — composes children via flex (vertical/horizontal) or
 * grid. The agent hands us a tree; we recurse via `ctx.render` so
 * arbitrary nesting works (e.g. a horizontal layout of a Markdown block
 * + a vertical layout of buttons + a Vega chart).
 *
 * `gap` is in Tailwind's 0.25rem unit (gap=4 → 1rem). We map it via the
 * inline `gap` style instead of a class so non-standard values pass
 * through (Tailwind JIT can't pick up a dynamic class name like
 * `gap-${n}`).
 */
import type { CSSProperties } from "react";

import { cn } from "@/lib/utils";

import { registerRenderer, type UIComponentSpec, type UIRenderer } from "./registry";

interface LayoutData {
  direction?: "vertical" | "horizontal" | "grid";
  gap?: number;
  align?: "start" | "center" | "end" | "stretch" | "baseline";
  justify?: "start" | "center" | "end" | "between" | "around" | "evenly";
  grid_columns?: number;
  children?: UIComponentSpec[];
}

const ALIGN: Record<string, string> = {
  start: "items-start",
  center: "items-center",
  end: "items-end",
  stretch: "items-stretch",
  baseline: "items-baseline",
};

const JUSTIFY: Record<string, string> = {
  start: "justify-start",
  center: "justify-center",
  end: "justify-end",
  between: "justify-between",
  around: "justify-around",
  evenly: "justify-evenly",
};

const LayoutRenderer: UIRenderer<LayoutData> = (spec, ctx) => {
  const data = spec.data ?? {};
  const direction = data.direction ?? "vertical";
  const gap = typeof data.gap === "number" ? data.gap : 2;
  const children = Array.isArray(data.children) ? data.children : [];

  const alignClass = data.align ? ALIGN[data.align] ?? "" : "";
  const justifyClass = data.justify ? JUSTIFY[data.justify] ?? "" : "";

  // Tailwind's gap-{n} unit is 0.25rem. We compute the rem inline so
  // arbitrary numeric `gap` values from the agent round-trip without
  // depending on Tailwind's safelist.
  const style: CSSProperties = { gap: `${gap * 0.25}rem` };

  let containerClass: string;
  if (direction === "horizontal") {
    containerClass = "flex flex-row flex-wrap";
  } else if (direction === "grid") {
    const cols = Math.max(1, data.grid_columns ?? 2);
    containerClass = "grid";
    style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
  } else {
    containerClass = "flex flex-col";
  }

  return (
    <div
      className={cn("w-full", containerClass, alignClass, justifyClass)}
      style={style}
    >
      {children.map((child, idx) => {
        if (!child || typeof child !== "object") return null;
        const key = child.component_id ?? `child-${idx}`;
        return <div key={key}>{ctx.render(child)}</div>;
      })}
    </div>
  );
};

registerRenderer("layout", LayoutRenderer);
export default LayoutRenderer;
