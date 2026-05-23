"use client";

/**
 * EditorPanel — dockview adapter for {@link EditorTab}.
 *
 * Tab-level metadata for the editor (the path to focus on) lives in
 * `params.tab.content_ref.path`. {@link EditorTab} doesn't take a `path`
 * prop today — it discovers the file via `useSidecar` events — so we
 * leave the inner component unchanged for this migration. Once the
 * editor learns to honour `path`, plumb it through here.
 */
import type { IDockviewPanelProps } from "dockview-react";

import { EditorTab } from "../EditorTab";
import type { PanelParams } from "./types";

export function EditorPanel(props: IDockviewPanelProps<PanelParams>) {
  const { sessionId } = props.params;
  return <EditorTab sessionId={sessionId} />;
}
