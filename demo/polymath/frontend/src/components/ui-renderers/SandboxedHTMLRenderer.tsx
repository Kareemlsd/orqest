"use client";

/**
 * SandboxedHTMLRenderer — Layer 3 renderer for agent-emitted HTML.
 *
 * Backend contract (`SandboxedHTMLComponentData`):
 *   { html: string, height_px: number, csp_extra?: string }
 *
 * Security model:
 *   - The HTML is wrapped in a full `<!doctype html>` document and rendered
 *     into an iframe via `srcDoc`.
 *   - `sandbox="allow-scripts"` — scripts run inside the iframe but cannot
 *     reach the parent document (no `allow-same-origin`). This is the
 *     standard "untrusted code" sandbox shape.
 *   - A Content-Security-Policy is injected via `<meta http-equiv>`
 *     because `srcDoc` doesn't let us set response headers. Modern browsers
 *     respect this for CSP.
 *
 * Default CSP:
 *   - `default-src 'none'`        — no fetches by default
 *   - `img-src data: https:`      — data URIs + HTTPS images
 *   - `style-src 'unsafe-inline'` — agent inlines styles
 *   - `script-src 'unsafe-inline'`— agent inlines scripts
 *   - `font-src data: https:`     — fonts via data URI / HTTPS
 *   The agent can extend (not relax) by passing `csp_extra`.
 *
 * Feature gate:
 *   - This renderer is gated behind the `sandboxed_html` feature flag from
 *     `useFeatureFlags()`. If the flag is off (default), we render an
 *     informational placeholder explaining how to enable it. This way the
 *     dispatcher doesn't blow up if the backend emits a sandboxed_html spec
 *     without the env var being set.
 */
import { registerRenderer, type UIRenderer } from "./registry";
import { useFeatureFlags } from "@/hooks/useFeatureFlags";

interface SandboxedHTMLData {
  html: string;
  height_px: number;
  csp_extra?: string;
}

const DEFAULT_CSP = [
  "default-src 'none'",
  "img-src data: https:",
  "style-src 'unsafe-inline'",
  "script-src 'unsafe-inline'",
  "font-src data: https:",
].join("; ");

const SandboxedHTMLRenderer: UIRenderer<SandboxedHTMLData> = (spec) => {
  const flags = useFeatureFlags();

  if (!flags.sandboxed_html) {
    return (
      <div className="rounded-md border border-dashed border-border-default p-3">
        <div className="font-mono text-[11px] text-muted-foreground">
          Sandboxed HTML is disabled. Set
          <code className="mx-1 bg-surface-code px-1 rounded">
            POLYMATH_ENABLE_SANDBOXED_HTML=1
          </code>
          on the backend to enable.
        </div>
      </div>
    );
  }

  const csp = spec.data.csp_extra
    ? `${DEFAULT_CSP}; ${spec.data.csp_extra}`
    : DEFAULT_CSP;

  // Escape only `"` in the CSP since we're embedding it in a quoted attr.
  // The `<meta>` tag is the only place CSP can land for srcdoc iframes.
  const cspAttr = csp.replace(/"/g, "&quot;");

  const wrapped = `<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<meta http-equiv="Content-Security-Policy" content="${cspAttr}" />
<style>
  html, body { margin: 0; padding: 0; font-family: ui-sans-serif, system-ui; color: inherit; }
</style>
</head>
<body>${spec.data.html}</body>
</html>`;

  return (
    <iframe
      title={`sandboxed-${spec.component_id}`}
      srcDoc={wrapped}
      sandbox="allow-scripts"
      className="w-full border border-border-subtle rounded-md bg-white"
      style={{ height: `${spec.data.height_px}px` }}
    />
  );
};

registerRenderer("sandboxed_html", SandboxedHTMLRenderer);
export default SandboxedHTMLRenderer;
