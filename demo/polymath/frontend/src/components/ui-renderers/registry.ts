"use client";

/**
 * registry — shared renderer registry for the generative UI dispatcher.
 *
 * Layer 1 (Layout/Text/Markdown/Image/Badge/Button/Input) and Layer 2/3
 * (Vega/Mermaid/Latex/JsonViewer/SandboxedHTML) renderers both register
 * themselves via `registerRenderer(...)` at module-load time. The
 * dispatcher (`UIComponentRenderer`) looks up renderers by
 * `component_type` on each spec it receives.
 *
 * `applyDelta` is re-exported from `useUIComponents.ts` so consumers of
 * this module (the recursive renderer + `useAllUIComponents`) don't need
 * to know which file owns the immutable patch logic. Single source of
 * truth lives in `useUIComponents.ts` to avoid drift between the
 * type-scoped and type-wildcard hooks.
 */
import type { ReactNode } from "react";

export {
  applyDelta,
  type UIComponentSpec,
  type UIDeltaEvent,
} from "@/hooks/useUIComponents";

import type { UIComponentSpec } from "@/hooks/useUIComponents";

export type UIRenderer<T = unknown> = (
  spec: UIComponentSpec<T>,
  context: RenderContext,
) => ReactNode;

/**
 * Passed to every renderer — provides the recursive dispatcher
 * + a session id for renderers that need to fetch artifacts / fire
 * callbacks.
 */
export interface RenderContext {
  sessionId: string;
  /**
   * Recursive entry point. Layout-style renderers call this on each
   * child to dispatch back through the registry.
   */
  render: (spec: UIComponentSpec) => ReactNode;
  /**
   * POST a button/input event back to the backend. Used by interactive
   * renderers (button click, input change).
   */
  emitEvent: (eventName: string, payload: Record<string, unknown>) => Promise<void>;
}

const RENDERERS = new Map<string, UIRenderer<unknown>>();

export function registerRenderer<T = unknown>(
  componentType: string,
  renderer: UIRenderer<T>,
): void {
  RENDERERS.set(componentType, renderer as UIRenderer<unknown>);
}

export function getRenderer(componentType: string): UIRenderer<unknown> | undefined {
  return RENDERERS.get(componentType);
}

export function listRegisteredTypes(): string[] {
  return Array.from(RENDERERS.keys()).sort();
}
