"use client";

/**
 * useTabs — bridge between the backend tabs manifest, the dockview
 * workspace, and the small slice of local state that doesn't live in
 * either place.
 *
 * Stream-2 of the dockview migration: this hook no longer owns
 * `tabs`, `byId`, `activeTabId`, `closeTab`, `focusTab`, `patchTab`, or
 * `reorder` — dockview is now the source of truth for the open-set,
 * activation, ordering, and per-panel close lifecycle. What remains:
 *
 *   1. **Hydrate on mount.** GET `/sessions/{sid}/tabs`, then for each
 *      `status='open'` row call `addPanel(...)` on the dockview API in
 *      `position` order. Set the active panel to `active_tab_id`.
 *   2. **SSE -> dockview.** Live-merge `tab.{opened,updated,closed,
 *      focused,restored}` into the dockview panel set, while tracking
 *      `lastClosed` / `recentlyClosed` / `unreadTabIds` locally for the
 *      undo-toast and recently-closed surfaces.
 *   3. **dockview -> REST.** Subscribe to `onDidActivePanelChange`,
 *      `onDidRemovePanel`, and `onDidLayoutChange`; forward user-driven
 *      changes back to the backend so other browser tabs of the same
 *      session stay coherent.
 *   4. **Mutations the workspace doesn't own.** `openTab` (creates a
 *      new row; the `tab.opened` SSE then spawns the panel) and
 *      `restoreTab` (POST `/restore`, then re-add the panel via the
 *      dockview API; mirrors `tab.restored` behaviour).
 *
 * Echo suppression: every dockview-bound REST mutation is tracked in
 * a per-event-type set so the immediate SSE re-broadcast doesn't loop
 * back into another REST call. Same on the inbound side — when SSE
 * tells us to focus or close a panel, we mark the upcoming dockview
 * event so its callback short-circuits.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";

import type { DockviewApi, IDockviewPanel } from "dockview-react";

import { backendBase } from "@/lib/api";
import type { AgentEvent } from "@/lib/events";

import { useSidecar } from "./useSidecar";

/** A row from the `tabs` table, projected to the JSON shape the router emits. */
export interface Tab {
  id: string;
  session_id: string;
  kind:
    | "shell"
    | "files"
    | "browser"
    | "editor"
    | "chart_gallery"
    | "report"
    | "memory"
    | "agents"
    | "component";
  title: string;
  position: number;
  pinned: boolean;
  status: "open" | "closed";
  content_ref: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  last_activity_at: string;
  closed_at: string | null;
}

interface ListResponse {
  tabs: Tab[];
  active_tab_id: string | null;
}

interface CreateOptions {
  kind: string;
  title: string;
  content_ref?: Record<string, unknown>;
}

/** Shape passed as `params` to every dockview panel adapter. The
 *  panel adapter (built in stream 1) reads `tab` to render content
 *  and `sessionId` to scope further requests. */
export interface PanelParams extends Record<string, unknown> {
  sessionId: string;
  tab: Tab;
}

export interface UseTabsResult {
  /** The most recently closed tab — `null` if none. Drives the
   *  "Tab closed - Undo" toast. */
  lastClosed: Tab | null;
  /** Closed-and-tombstoned tabs (within 24 h), newest-closed first.
   *  Drives the recently-closed menu. */
  recentlyClosed: Tab[];
  /** Acknowledge the most recent close so the toast hides. */
  ackLastClose: () => void;
  /** POST `/restore`, then re-add the panel via the dockview API. */
  restoreTab: (id: string) => Promise<void>;
  /** POST to create a new tab; the inbound `tab.opened` SSE event
   *  spawns the panel via `addPanel`. */
  openTab: (opts: CreateOptions) => Promise<void>;
  /** Tab ids the user hasn't seen activity on since they last viewed
   *  them — for badging inactive panels. */
  unreadTabIds: ReadonlySet<string>;
}

/**
 * Convert a tab row into the `addPanel` argument for dockview. Kept
 * as a free function so both the hydrate path and the SSE-driven path
 * use the exact same shape.
 *
 * Crucial: dockview's default for ``addPanel(...)`` is **"new group"**
 * — every panel without an explicit ``position`` ends up in its own
 * splitview cell. To get the familiar single-tab-strip topology we
 * always anchor against an existing group when one is present. The
 * very first call returns no ``position`` (no anchor exists yet) so
 * dockview seeds the first group naturally.
 */
function panelOptionsFor(api: DockviewApi, sessionId: string, tab: Tab) {
  const params: PanelParams = { sessionId, tab };
  const referenceGroup = api.activeGroup ?? api.groups[0];
  return {
    id: tab.id,
    component: tab.kind,
    title: tab.title,
    params,
    ...(referenceGroup
      ? { position: { referenceGroup } as const }
      : {}),
  };
}

export function useTabs(
  sessionId: string,
  dockviewApiRef: MutableRefObject<DockviewApi | null>,
): UseTabsResult {
  // Tab map kept just for the close-history surfaces (`recentlyClosed`,
  // `lastClosed`). dockview owns the live open-set; this map only ever
  // adds rows and flips them to `closed`.
  const [byId, setById] = useState<Map<string, Tab>>(() => new Map());
  const [unreadTabIds, setUnreadTabIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [lastClosed, setLastClosed] = useState<Tab | null>(null);
  const [recentlyClosed, setRecentlyClosed] = useState<Tab[]>([]);

  // Tracks the currently-active panel id without triggering renders.
  // Used to decide whether incoming `tab.opened` / `tab.updated` events
  // should mark the affected tab as "unread".
  const activePanelIdRef = useRef<string | null>(null);

  // ---- Echo-suppression sets ------------------------------------------
  //
  // Each set guards one direction of round-trip. When we issue a REST
  // mutation that we know will come back as an SSE event, we add the
  // affected id to the matching set; the SSE handler checks the set
  // before mutating dockview and unmarks if it finds a hit.
  //
  // Symmetrically, when we apply an SSE-driven dockview mutation, we
  // mark the same id so the dockview event listener (focus/close/
  // reorder -> REST) skips its outbound REST call once.
  //
  // The sets live in refs so updates don't drive renders and so the
  // dockview event listeners (registered in a separate effect) see the
  // current values.
  const ignoreNextFocus = useRef<Set<string>>(new Set());
  const ignoreNextClose = useRef<Set<string>>(new Set());
  const ignoreNextLayoutChange = useRef<boolean>(false);

  // The last-seen panel order. We only POST `/reorder` when the
  // dockview layout actually moves a panel — `onDidLayoutChange` fires
  // for every kind of layout mutation including resize and active
  // change, so we have to compare against the last known order to
  // decide whether a reorder REST call is warranted.
  const lastOrderRef = useRef<string[]>([]);

  // ---- Hydrate on mount ------------------------------------------------
  //
  // Wait for the dockview API to be present before we GET the manifest
  // — without it we'd buffer rows we can't render. Polling via a tight
  // effect re-run is fine: dockview attaches the api ref synchronously
  // on first mount, so this should resolve in one tick.

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    let pollHandle: ReturnType<typeof setTimeout> | null = null;

    const tryHydrate = async () => {
      const api = dockviewApiRef.current;
      if (!api) {
        // dockview hasn't mounted yet — re-check next macrotask.
        pollHandle = setTimeout(tryHydrate, 16);
        return;
      }
      try {
        const resp = await fetch(
          `${backendBase()}/sessions/${sessionId}/tabs`,
        );
        if (!resp.ok) return;
        const payload = (await resp.json()) as ListResponse;
        if (cancelled) return;

        const next = new Map<string, Tab>();
        for (const t of payload.tabs) next.set(t.id, t);
        setById(next);

        // Apply ordering: sort by position, then add in order so each
        // call inserts at the end. Each addPanel emits an
        // onDidLayoutChange — suppress those so we don't immediately
        // re-POST the same order back at the backend.
        const ordered = payload.tabs
          .filter((t) => t.status === "open")
          .sort((a, b) => a.position - b.position);

        for (const tab of ordered) {
          if (api.getPanel(tab.id)) continue;
          ignoreNextLayoutChange.current = true;
          api.addPanel({ ...panelOptionsFor(api, sessionId, tab), inactive: true });
        }

        // Set active panel: the manifest's `active_tab_id` if open,
        // otherwise the first one. Suppress the resulting focus echo.
        const activeId =
          payload.active_tab_id &&
          ordered.find((t) => t.id === payload.active_tab_id)
            ? payload.active_tab_id
            : ordered[0]?.id ?? null;
        if (activeId) {
          ignoreNextFocus.current.add(activeId);
          api.getPanel(activeId)?.api.setActive();
          activePanelIdRef.current = activeId;
        }

        // Snapshot the order so onDidLayoutChange can detect real
        // moves vs. activation events.
        lastOrderRef.current = ordered.map((t) => t.id);
      } catch {
        // SSE will populate once events arrive.
      }
    };

    tryHydrate();
    return () => {
      cancelled = true;
      if (pollHandle) clearTimeout(pollHandle);
    };
  }, [sessionId, dockviewApiRef]);

  // ---- SSE -> dockview ------------------------------------------------

  useSidecar(sessionId, (evt: AgentEvent) => {
    const et = evt.event_type;
    if (
      et !== "tab.opened" &&
      et !== "tab.updated" &&
      et !== "tab.closed" &&
      et !== "tab.focused" &&
      et !== "tab.restored"
    ) {
      return;
    }
    const data = evt.data as unknown as Tab | { id?: string };
    const id = (data as Tab)?.id;
    if (!id) return;

    const api = dockviewApiRef.current;

    // Always update the local map so close-history surfaces stay
    // accurate even if dockview isn't mounted yet.
    setById((prev) => {
      const next = new Map(prev);
      next.set(id, data as Tab);
      return next;
    });

    if (et === "tab.opened" || et === "tab.restored") {
      const tab = data as Tab;
      if (api && !api.getPanel(id)) {
        // Skip if the user/agent created it locally and dockview
        // already has the panel — avoids the echo loop.
        ignoreNextLayoutChange.current = true;
        api.addPanel(panelOptionsFor(api, sessionId, tab));
      }
      // Newly-opened (background) tab is unread until viewed.
      if (id !== activePanelIdRef.current) {
        setUnreadTabIds((prev) => {
          if (prev.has(id)) return prev;
          const next = new Set(prev);
          next.add(id);
          return next;
        });
      }
      // A `tab.restored` carries a row that was previously in the
      // recentlyClosed list — remove it so the menu drops the entry.
      if (et === "tab.restored") {
        setRecentlyClosed((prev) => prev.filter((t) => t.id !== id));
        if (lastClosed?.id === id) setLastClosed(null);
      }
      return;
    }

    if (et === "tab.updated") {
      const tab = data as Tab;
      if (api) {
        const panel = api.getPanel(id);
        if (panel) {
          if (tab.title !== panel.title) panel.api.setTitle(tab.title);
          // Always push fresh params — adapters re-render off `tab`.
          const params: PanelParams = { sessionId, tab };
          panel.api.updateParameters(params);
        }
      }
      // Mark non-active updated tabs as unread.
      if (id !== activePanelIdRef.current) {
        setUnreadTabIds((prev) => {
          if (prev.has(id)) return prev;
          const next = new Set(prev);
          next.add(id);
          return next;
        });
      }
      return;
    }

    if (et === "tab.focused") {
      // Focus event: tell dockview to make this panel active, but only
      // if it isn't already (otherwise we'd burn an event for nothing).
      activePanelIdRef.current = id;
      // Newly focused tab is now read.
      setUnreadTabIds((prev) => {
        if (!prev.has(id)) return prev;
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      if (api) {
        const panel = api.getPanel(id);
        if (panel && !panel.api.isActive) {
          ignoreNextFocus.current.add(id);
          panel.api.setActive();
        }
      }
      return;
    }

    if (et === "tab.closed") {
      const tab = data as Tab;
      if (api) {
        const panel = api.getPanel(id);
        if (panel) {
          ignoreNextClose.current.add(id);
          ignoreNextLayoutChange.current = true;
          panel.api.close();
        }
      }
      if (activePanelIdRef.current === id) activePanelIdRef.current = null;
      setLastClosed(tab);
      setRecentlyClosed((prev) => {
        const filtered = prev.filter((t) => t.id !== id);
        return [tab, ...filtered];
      });
      // Closed tabs aren't badge targets anymore.
      setUnreadTabIds((prev) => {
        if (!prev.has(id)) return prev;
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      return;
    }
  });

  // ---- dockview -> REST -----------------------------------------------
  //
  // Subscribe once the api ref becomes non-null. The effect re-runs
  // whenever `sessionId` changes; dockview is mounted by the parent
  // <DockviewWorkspace> so by the time anything calls our returned
  // `openTab` / `restoreTab` the api should already be there.

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    let disposers: Array<() => void> = [];
    let pollHandle: ReturnType<typeof setTimeout> | null = null;

    const trySubscribe = () => {
      const api = dockviewApiRef.current;
      if (!api) {
        pollHandle = setTimeout(trySubscribe, 16);
        return;
      }
      if (cancelled) return;

      // Active panel changed (user clicked a tab, dockview moved focus
      // due to a close, etc.) -> POST /focus, suppressing any echo
      // that we ourselves triggered through SSE handling.
      const activeSub = api.onDidActivePanelChange(
        (panel: IDockviewPanel | undefined) => {
          if (!panel) {
            activePanelIdRef.current = null;
            return;
          }
          const id = panel.id;
          if (ignoreNextFocus.current.has(id)) {
            ignoreNextFocus.current.delete(id);
            activePanelIdRef.current = id;
            return;
          }
          if (activePanelIdRef.current === id) return;
          activePanelIdRef.current = id;
          // Clear unread for the now-active tab even before the SSE
          // round-trip — keeps the badge update tight.
          setUnreadTabIds((prev) => {
            if (!prev.has(id)) return prev;
            const next = new Set(prev);
            next.delete(id);
            return next;
          });
          fetch(
            `${backendBase()}/sessions/${sessionId}/tabs/${id}/focus`,
            { method: "POST" },
          ).catch(() => {
            // Best-effort — the SSE bus stays the source of truth.
          });
        },
      );
      disposers.push(() => activeSub.dispose());

      // Panel removal (user clicked the X, dockview closed it via
      // panel.api.close(), keyboard shortcut, etc.) -> DELETE.
      const removeSub = api.onDidRemovePanel((panel: IDockviewPanel) => {
        const id = panel.id;
        if (ignoreNextClose.current.has(id)) {
          ignoreNextClose.current.delete(id);
          return;
        }
        fetch(
          `${backendBase()}/sessions/${sessionId}/tabs/${id}`,
          { method: "DELETE" },
        ).catch(() => {
          // Best-effort.
        });
      });
      disposers.push(() => removeSub.dispose());

      // Layout changed -> figure out the current panel order; if it
      // differs from the last snapshot, POST /reorder. Skip when the
      // hook itself triggered the change (set `ignoreNextLayoutChange`
      // before the dockview call).
      const layoutSub = api.onDidLayoutChange(() => {
        if (ignoreNextLayoutChange.current) {
          ignoreNextLayoutChange.current = false;
          // Even when suppressed, refresh the order snapshot so the
          // next real reorder compares against the right baseline.
          lastOrderRef.current = api.panels.map((p) => p.id);
          return;
        }
        const currentOrder = api.panels.map((p) => p.id);
        const prevOrder = lastOrderRef.current;
        const sameOrder =
          currentOrder.length === prevOrder.length &&
          currentOrder.every((id, idx) => prevOrder[idx] === id);
        if (sameOrder) return;
        lastOrderRef.current = currentOrder;
        fetch(
          `${backendBase()}/sessions/${sessionId}/tabs/reorder`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ order: currentOrder }),
          },
        ).catch(() => {
          // Best-effort.
        });
      });
      disposers.push(() => layoutSub.dispose());
    };

    trySubscribe();
    return () => {
      cancelled = true;
      if (pollHandle) clearTimeout(pollHandle);
      for (const dispose of disposers) {
        try {
          dispose();
        } catch {
          // Ignore — disposers are best-effort.
        }
      }
      disposers = [];
    };
  }, [sessionId, dockviewApiRef]);

  // ---- Mutations exposed to consumers ---------------------------------

  const ackLastClose = useCallback(() => {
    setLastClosed(null);
  }, []);

  const openTab = useCallback(
    async (opts: CreateOptions): Promise<void> => {
      try {
        const resp = await fetch(
          `${backendBase()}/sessions/${sessionId}/tabs`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(opts),
          },
        );
        if (!resp.ok) return;
        // Backend will fan out a `tab.opened` SSE event which the
        // handler above turns into an addPanel. We still parse the
        // response to seed `byId` immediately so close-history
        // surfaces don't have to wait for the round-trip.
        const tab = (await resp.json()) as Tab;
        setById((prev) => {
          const next = new Map(prev);
          next.set(tab.id, tab);
          return next;
        });
      } catch {
        // No-op.
      }
    },
    [sessionId],
  );

  const restoreTab = useCallback(
    async (id: string): Promise<void> => {
      try {
        const resp = await fetch(
          `${backendBase()}/sessions/${sessionId}/tabs/${id}/restore`,
          { method: "POST" },
        );
        if (!resp.ok) return;
        const tab = (await resp.json()) as Tab;
        setById((prev) => {
          const next = new Map(prev);
          next.set(tab.id, tab);
          return next;
        });
        // Optimistically drop from recentlyClosed; the SSE
        // `tab.restored` handler does the same idempotently.
        setRecentlyClosed((prev) => prev.filter((t) => t.id !== id));
        if (lastClosed?.id === id) setLastClosed(null);
        // Re-add the panel directly — the `tab.restored` SSE handler
        // is idempotent (`api.getPanel(id)` guard), so racing with it
        // is safe.
        const api = dockviewApiRef.current;
        if (api && !api.getPanel(id)) {
          ignoreNextLayoutChange.current = true;
          api.addPanel(panelOptionsFor(api, sessionId, tab));
        }
      } catch {
        // No-op.
      }
    },
    [sessionId, dockviewApiRef, lastClosed],
  );

  // Prune `recentlyClosed` to the 24 h window the backend honors.
  // Recompute on every render — cheap, the list is small. Using a
  // useMemo would only complicate the dependency surface.
  const dayMs = 24 * 60 * 60 * 1000;
  const now = Date.now();
  const filteredRecentlyClosed = recentlyClosed.filter((t) => {
    if (!t.closed_at) return false;
    return now - Date.parse(t.closed_at) < dayMs;
  });

  return {
    lastClosed,
    recentlyClosed: filteredRecentlyClosed,
    ackLastClose,
    restoreTab,
    openTab,
    unreadTabIds,
  };
}
