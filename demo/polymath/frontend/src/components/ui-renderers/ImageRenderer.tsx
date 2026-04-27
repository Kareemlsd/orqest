"use client";

/**
 * ImageRenderer — `<img>` with an optional caption, max-height/width
 * clamps, and backend-base prefixing for relative paths.
 *
 * URL prefixing rule: any URL starting with "/" is treated as a
 * backend-relative path and gets the API base prepended (matches how
 * `ChartsTab` resolves `/sessions/{sid}/artifacts/...`). Absolute URLs
 * (`http://`, `https://`, `data:`) pass through untouched. This keeps
 * the agent's output portable — it can emit `/sessions/.../artifacts/x`
 * without knowing the frontend's deploy path.
 */
import type { CSSProperties } from "react";

import { backendBase } from "@/lib/api";

import { registerRenderer, type UIRenderer } from "./registry";

interface ImageData {
  url?: string;
  alt?: string;
  caption?: string;
  max_height_px?: number;
  max_width_px?: number;
}

function resolveUrl(url: string): string {
  if (!url) return url;
  // Absolute (incl. data: + protocol-relative). Pass through.
  if (
    url.startsWith("http://") ||
    url.startsWith("https://") ||
    url.startsWith("data:") ||
    url.startsWith("//")
  ) {
    return url;
  }
  // Backend-relative.
  if (url.startsWith("/")) {
    return `${backendBase()}${url}`;
  }
  // Anything else (relative without leading slash) — leave alone; the
  // browser will resolve against the current page.
  return url;
}

const ImageRenderer: UIRenderer<ImageData> = (spec) => {
  const data = spec.data ?? {};
  const src = data.url ? resolveUrl(data.url) : "";
  const alt = data.alt ?? "";
  const caption = data.caption ?? "";

  const style: CSSProperties = {};
  if (typeof data.max_height_px === "number") {
    style.maxHeight = `${data.max_height_px}px`;
  }
  if (typeof data.max_width_px === "number") {
    style.maxWidth = `${data.max_width_px}px`;
  }

  if (!src) {
    return (
      <div className="font-mono text-[10px] text-muted-foreground italic">
        (image: no url)
      </div>
    );
  }

  return (
    <figure className="flex flex-col items-start gap-1.5">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={alt}
        style={style}
        className="rounded-md border border-border-subtle bg-surface-card max-w-full h-auto"
      />
      {caption && (
        <figcaption className="font-mono text-[11px] text-muted-foreground">
          {caption}
        </figcaption>
      )}
    </figure>
  );
};

registerRenderer("image", ImageRenderer);
export default ImageRenderer;
