/**
 * Dockview panel registry — keys MUST match the seven `Tab["kind"]`
 * discriminators in `useTabs.ts` exactly. The integration agent's
 * `useTabs` hook reads this map to resolve a tab to its panel renderer.
 */
import type { IDockviewReactProps } from "dockview-react";

import { AgentsPanel } from "./AgentsPanel";
import { BrowserPanel } from "./BrowserPanel";
import { ChartGalleryPanel } from "./ChartGalleryPanel";
import { ComponentTabPanel } from "./ComponentTabPanel";
import { EditorPanel } from "./EditorPanel";
import { FilesPanel } from "./FilesPanel";
import { MemoryPanel } from "./MemoryPanel";
import { ReportPanel } from "./ReportPanel";
import { ShellPanel } from "./ShellPanel";

export type { PanelParams } from "./types";

export const PANEL_COMPONENTS: IDockviewReactProps["components"] = {
  shell: ShellPanel,
  files: FilesPanel,
  browser: BrowserPanel,
  editor: EditorPanel,
  chart_gallery: ChartGalleryPanel,
  report: ReportPanel,
  // Cognitive surfaces (Phase A scaffolds; B/C/D/E flesh them out).
  memory: MemoryPanel,
  agents: AgentsPanel,
  component: ComponentTabPanel,
};

export {
  AgentsPanel,
  BrowserPanel,
  ChartGalleryPanel,
  ComponentTabPanel,
  EditorPanel,
  FilesPanel,
  MemoryPanel,
  ReportPanel,
  ShellPanel,
};
