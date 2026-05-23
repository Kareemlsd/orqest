"use client";

/**
 * JsonViewerRenderer — Layer 2 renderer for arbitrary JSON payloads with
 * collapsible nodes.
 *
 * Backend contract (`JsonViewerComponentData`):
 *   { data: unknown, expanded_paths: string[], title?: string }
 *
 * Library: `@uiw/react-json-view`. Chosen because it ships with built-in
 * collapse/expand UI and reasonable theming defaults out of the box; no
 * extra CSS work needed to look right against the canvas.
 *
 * `expanded_paths` semantics:
 *   - Each entry is a dot-path (e.g. `"foo.bar.0.qux"`). When a path matches
 *     the node's keyid, it should render expanded; everything else respects
 *     the default collapse depth (`collapsed={2}`).
 *   - `@uiw/react-json-view` exposes this via `shouldExpandNodeInitially`,
 *     which receives `keys: (number|string)[]` plus the level — we join the
 *     keys with `.` and check membership in the prefix-set.
 *
 * Defensive shaping:
 *   - The lib expects `value: object` (its prop type). If the agent emits
 *     a primitive (string / number) we wrap it as `{ value: <primitive> }`
 *     so the viewer doesn't blow up.
 */
import JsonView, {
  type ShouldExpandNodeInitially,
} from "@uiw/react-json-view";

import { registerRenderer, type UIRenderer } from "./registry";

interface JsonViewerData {
  data: unknown;
  expanded_paths: string[];
  title?: string;
}

function ensureObject(data: unknown): object {
  if (data !== null && typeof data === "object") return data;
  return { value: data };
}

function buildExpandPredicate(
  expandedPaths: string[],
): ShouldExpandNodeInitially<object> | undefined {
  if (!expandedPaths || expandedPaths.length === 0) return undefined;
  // Pre-compute a Set + a prefix-set: a node should be expanded if its path
  // is itself in the list OR is a prefix of any expanded path.
  const exact = new Set(expandedPaths);
  const prefixes = new Set<string>();
  for (const p of expandedPaths) {
    const parts = p.split(".");
    for (let i = 1; i <= parts.length; i++) {
      prefixes.add(parts.slice(0, i).join("."));
    }
  }
  return (isExpanded, { keys }) => {
    const path = keys.join(".");
    if (path === "") return isExpanded; // root — leave as default
    if (exact.has(path) || prefixes.has(path)) return true;
    return isExpanded;
  };
}

const JsonViewerRenderer: UIRenderer<JsonViewerData> = (spec) => {
  const value = ensureObject(spec.data.data);
  const shouldExpand = buildExpandPredicate(spec.data.expanded_paths ?? []);

  return (
    <div className="w-full text-[12px]">
      {spec.data.title && (
        <div className="font-mono text-[11px] text-muted-foreground mb-1">
          {spec.data.title}
        </div>
      )}
      <JsonView
        value={value}
        collapsed={shouldExpand ? false : 2}
        shouldExpandNodeInitially={shouldExpand}
        displayDataTypes={false}
        enableClipboard
      />
    </div>
  );
};

registerRenderer("json_viewer", JsonViewerRenderer);
export default JsonViewerRenderer;
