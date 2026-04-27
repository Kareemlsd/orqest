"use client";

/**
 * BrowserPanel — dockview adapter for {@link BrowserTab}. See
 * {@link ShellPanel} for the panel-contract rationale.
 */
import type { IDockviewPanelProps } from "dockview-react";

import { BrowserTab } from "../BrowserTab";
import type { PanelParams } from "./types";

export function BrowserPanel(props: IDockviewPanelProps<PanelParams>) {
  const { sessionId } = props.params;
  return <BrowserTab sessionId={sessionId} />;
}
