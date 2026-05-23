"use client";

/**
 * ChartGalleryPanel — dockview adapter for {@link ChartsTab}, the
 * `chart_gallery` `kind`'s renderer. See {@link ShellPanel} for the
 * panel-contract rationale.
 */
import type { IDockviewPanelProps } from "dockview-react";

import { ChartsTab } from "../ChartsTab";
import type { PanelParams } from "./types";

export function ChartGalleryPanel(props: IDockviewPanelProps<PanelParams>) {
  const { sessionId } = props.params;
  return <ChartsTab sessionId={sessionId} />;
}
