"use client";

/**
 * ShellPanel — dockview adapter that mounts {@link ShellTab} as a panel.
 *
 * The dockview panel API hands us an {@link IDockviewPanelProps} with
 * a typed `params` payload owned by whoever added the panel (here,
 * `useTabs` writes `sessionId` + the full {@link Tab} row so panels can
 * read tab-level metadata when they need it). The inner component takes
 * only what it needs — `ShellTab` cares about `sessionId`.
 */
import type { IDockviewPanelProps } from "dockview-react";

import { ShellTab } from "../ShellTab";
import type { PanelParams } from "./types";

export function ShellPanel(props: IDockviewPanelProps<PanelParams>) {
  const { sessionId } = props.params;
  return <ShellTab sessionId={sessionId} />;
}
