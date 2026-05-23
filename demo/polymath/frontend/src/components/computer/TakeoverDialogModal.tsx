"use client";

/**
 * TakeoverDialogModal — agent-initiated user prompt.
 *
 * Subscribes to `ui.takeover_dialog.{init,delta,remove}` events for the
 * session. When a `TakeoverDialogComponent` arrives, surfaces it as a
 * modal asking the user to confirm an action, supply input, or pick
 * from a list of choices. The user's response is POSTed back to the
 * backend, which is expected to emit `<response_event>` (default
 * `takeover.responded`) on the EventBus so the agent loop can resume.
 *
 * Coexists with `TakeoverButton.tsx` — that button is the always-on
 * user-initiated affordance (pause-the-agent), this modal pops up when
 * the *agent* needs the user's input mid-run.
 *
 * The backend response endpoint (`POST /sessions/{sid}/takeover/respond`)
 * is forward-compat — it does not exist yet. Until it ships, response
 * submissions will 404; we log a warning and close the modal locally.
 */
import { useCallback, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { useUIComponents } from "@/hooks/useUIComponents";
import { backendBase } from "@/lib/api";

type TakeoverKind = "confirm" | "input" | "choice";

interface TakeoverDialogData {
  kind: TakeoverKind;
  title: string;
  message: string;
  choices: string[];
  confirm_label: string;
  cancel_label: string;
  response_event: string;
}

interface TakeoverResponsePayload {
  type: "confirm" | "cancel" | "input" | "choice";
  value?: string;
}

async function postResponse(
  sessionId: string,
  componentId: string,
  response: TakeoverResponsePayload,
): Promise<void> {
  try {
    const resp = await fetch(
      `${backendBase()}/sessions/${sessionId}/takeover/respond`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ component_id: componentId, response }),
      },
    );
    if (!resp.ok) {
      // The backend endpoint is not yet implemented (Phase δ TODO). Log
      // and degrade gracefully — the modal still closes locally so the
      // user isn't blocked.
      console.warn(
        `[TakeoverDialogModal] response endpoint returned ${resp.status}; backend wiring TODO`,
      );
    }
  } catch (err) {
    console.warn(
      "[TakeoverDialogModal] failed to POST takeover response",
      err,
    );
  }
}

export function TakeoverDialogModal({ sessionId }: { sessionId: string }) {
  const { components } = useUIComponents<TakeoverDialogData>(
    sessionId,
    "takeover_dialog",
  );

  // Track locally-dismissed component IDs so we don't re-render after
  // the user responds. The backend may also emit a `ui.takeover_dialog.remove`
  // event, which `useUIComponents` already handles — this set is a
  // belt-and-braces optimistic dismissal that doesn't wait for the
  // server round trip.
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(
    () => new Set(),
  );

  // Newest non-dismissed dialog wins. `components` is already sorted
  // newest-first by `useUIComponents`.
  const current = useMemo(
    () => components.find((c) => !dismissedIds.has(c.component_id)) ?? null,
    [components, dismissedIds],
  );

  const dismiss = useCallback((componentId: string) => {
    setDismissedIds((prev) => {
      if (prev.has(componentId)) return prev;
      const next = new Set(prev);
      next.add(componentId);
      return next;
    });
  }, []);

  const handleResponse = useCallback(
    async (componentId: string, response: TakeoverResponsePayload) => {
      // Optimistically dismiss before awaiting the network call so the
      // modal feels snappy.
      dismiss(componentId);
      await postResponse(sessionId, componentId, response);
    },
    [dismiss, sessionId],
  );

  if (!current) return null;

  const data = current.data;
  const open = true;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        // Closing via `Esc` / overlay click is treated as a cancel.
        if (!next) {
          void handleResponse(current.component_id, { type: "cancel" });
        }
      }}
    >
      <DialogContent className="bg-surface-elevated border-border-subtle">
        <DialogTitle className="font-serif text-lg leading-tight text-foreground">
          {data.title || "Action needed"}
        </DialogTitle>
        {data.message ? (
          <DialogDescription className="text-sm text-muted-foreground whitespace-pre-wrap">
            {data.message}
          </DialogDescription>
        ) : null}
        <DialogBody
          data={data}
          onSubmit={(response) => handleResponse(current.component_id, response)}
        />
      </DialogContent>
    </Dialog>
  );
}

interface DialogBodyProps {
  data: TakeoverDialogData;
  onSubmit: (response: TakeoverResponsePayload) => void;
}

function DialogBody({ data, onSubmit }: DialogBodyProps) {
  if (data.kind === "input") {
    return <InputBody data={data} onSubmit={onSubmit} />;
  }
  if (data.kind === "choice") {
    return <ChoiceBody data={data} onSubmit={onSubmit} />;
  }
  return <ConfirmBody data={data} onSubmit={onSubmit} />;
}

function ConfirmBody({ data, onSubmit }: DialogBodyProps) {
  return (
    <div className="flex justify-end gap-2 pt-2">
      <Button
        variant="outline"
        size="sm"
        onClick={() => onSubmit({ type: "cancel" })}
      >
        {data.cancel_label || "Cancel"}
      </Button>
      <Button
        variant="default"
        size="sm"
        onClick={() => onSubmit({ type: "confirm" })}
      >
        {data.confirm_label || "Continue"}
      </Button>
    </div>
  );
}

function InputBody({ data, onSubmit }: DialogBodyProps) {
  const [value, setValue] = useState("");
  const trimmed = value.trim();

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!trimmed) return;
        onSubmit({ type: "input", value: trimmed });
      }}
      className="flex flex-col gap-3 pt-1"
    >
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        autoFocus
        rows={4}
        className="w-full resize-y rounded-sm border border-border-subtle bg-surface-card px-3 py-2 text-sm text-foreground font-mono outline-none focus:border-accent"
        placeholder="Your response…"
      />
      <div className="flex justify-end gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => onSubmit({ type: "cancel" })}
        >
          {data.cancel_label || "Cancel"}
        </Button>
        <Button
          type="submit"
          variant="default"
          size="sm"
          disabled={!trimmed}
        >
          {data.confirm_label || "Submit"}
        </Button>
      </div>
    </form>
  );
}

function ChoiceBody({ data, onSubmit }: DialogBodyProps) {
  // Render one button per choice. Cancel remains available for users who
  // want to back out without picking. Empty `choices` falls back to a
  // confirm-only layout so the modal never traps the user.
  const choices = data.choices ?? [];

  if (choices.length === 0) {
    return <ConfirmBody data={data} onSubmit={onSubmit} />;
  }

  return (
    <div className="flex flex-col gap-3 pt-1">
      <ul className="flex flex-col gap-2">
        {choices.map((choice) => (
          <li key={choice}>
            <button
              type="button"
              onClick={() => onSubmit({ type: "choice", value: choice })}
              className="w-full text-left rounded-sm border border-border-subtle bg-surface-card px-3 py-2 text-sm text-foreground hover:border-accent hover:bg-surface-hover transition-colors"
            >
              {choice}
            </button>
          </li>
        ))}
      </ul>
      <div className="flex justify-end">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onSubmit({ type: "cancel" })}
        >
          {data.cancel_label || "Cancel"}
        </Button>
      </div>
    </div>
  );
}
