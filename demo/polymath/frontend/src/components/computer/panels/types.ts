/**
 * Shared panel-params shape for every dockview adapter in this folder.
 *
 * The contract with the {@link useTabs} hook (Stream 2): when adding a
 * panel, write `{ sessionId, tab }` as the panel's `params` so each
 * adapter has access to both the session id (for hooks like
 * `useSidecar`) and the tab row (for kinds like `component` whose
 * renderer needs `content_ref.component_ids`).
 */
import type { Tab } from "@/hooks/useTabs";

export interface PanelParams {
  sessionId: string;
  tab: Tab;
}
