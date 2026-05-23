"use client";

/**
 * ReportPanel — dockview adapter for {@link ReportTab}. See
 * {@link ShellPanel} for the panel-contract rationale.
 */
import type { IDockviewPanelProps } from "dockview-react";

import { ReportTab } from "../ReportTab";
import type { PanelParams } from "./types";

export function ReportPanel(props: IDockviewPanelProps<PanelParams>) {
  const { sessionId } = props.params;
  return <ReportTab sessionId={sessionId} />;
}
