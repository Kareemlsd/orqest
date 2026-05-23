"use client";

/**
 * FilesPanel — dockview adapter for {@link FilesTab}. See
 * {@link ShellPanel} for the panel-contract rationale.
 */
import type { IDockviewPanelProps } from "dockview-react";

import { FilesTab } from "../FilesTab";
import type { PanelParams } from "./types";

export function FilesPanel(props: IDockviewPanelProps<PanelParams>) {
  const { sessionId } = props.params;
  return <FilesTab sessionId={sessionId} />;
}
