"use client";

/**
 * ComponentTabPanel — dockview adapter for the `kind: "component"` tab.
 *
 * Wraps {@link TabComponentRenderer}, which needs the full {@link Tab}
 * row to resolve `content_ref.component_ids`. The dockview `params`
 * payload is the canonical source for that — `useTabs` mirrors the
 * latest `Tab` row onto the panel's params each time it patches.
 */
import type { IDockviewPanelProps } from "dockview-react";

import { TabComponentRenderer } from "../TabComponentRenderer";
import type { PanelParams } from "./types";

export function ComponentTabPanel(props: IDockviewPanelProps<PanelParams>) {
  const { sessionId, tab } = props.params;
  return <TabComponentRenderer sessionId={sessionId} tab={tab} />;
}
