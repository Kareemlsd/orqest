"use client";

/**
 * CheckpointDivider — a thin visual marker between assistant messages
 * where the agent's plan state shifted significantly.
 *
 * Detection (visual only this round):
 *   - Subscribes to `usePlan(sessionId)`.
 *   - Hashes the plan as `tasks.map(t => t.status).join('|')`.
 *   - When the hash changes, attribute the change to the *most recent*
 *     assistant message id observed at that moment. The next time
 *     `<CheckpointDivider afterMessageId={...} />` is rendered with
 *     that id, it returns a divider; otherwise it returns null.
 *
 * The actual restore wiring is phase-deferred: clicking `Restore here`
 * only logs a warning. Adding the affordance now keeps the design
 * intent visible without blocking the round on the backend contract.
 *
 * Module-level state cache is intentional: the divider needs to stay
 * stable across re-renders of unrelated messages, and the parent map
 * has no other natural place to colocate a per-session "checkpoint
 * stamp → message id" lookup.
 */
import { useMemo } from "react";

import {
  Checkpoint,
  CheckpointIcon,
  CheckpointTrigger,
} from "@/components/ai-elements/checkpoint";
import { usePlan } from "@/hooks/usePlan";
import type { Plan } from "@/lib/events";

interface CheckpointDividerProps {
  sessionId: string;
  afterMessageId: string;
  /** The most-recent assistant message id observed by the surrounding
   *  message map. Required so we can attribute plan-hash changes to a
   *  specific turn (the parent already has this info; we don't want to
   *  re-derive it inside every divider instance). */
  latestAssistantMessageId: string | null;
}

/**
 * Per-session map of `messageId → planHash` recorded at the moment the
 * hash flipped. Stays out of React state because it never affects
 * render — it only feeds the boolean check the divider does on render.
 */
const checkpointStamps = new Map<
  string /* sessionId */,
  Map<string /* messageId */, string /* planHash */>
>();

const lastHashBySession = new Map<string /* sessionId */, string>();

function planHash(plan: Plan): string {
  // Only status changes mark a checkpoint. Title/structure changes are
  // noisy; they tend to ride alongside status flips anyway.
  return plan.tasks.map((t) => `${t.id}:${t.status}`).join("|");
}

/**
 * Record a stamp for `messageId` when the plan hash actually changed
 * from the last observation. First observation isn't a checkpoint —
 * there's nothing to compare against. Module-level bookkeeping so it
 * survives React render cycles without polluting state.
 */
function stampCheckpointIfChanged(
  sessionId: string,
  hash: string,
  messageId: string,
): void {
  const prev = lastHashBySession.get(sessionId);
  if (prev === hash) return;
  lastHashBySession.set(sessionId, hash);
  if (prev === undefined) return;
  let stamps = checkpointStamps.get(sessionId);
  if (!stamps) {
    stamps = new Map();
    checkpointStamps.set(sessionId, stamps);
  }
  stamps.set(messageId, hash);
}

export function CheckpointDivider({
  sessionId,
  afterMessageId,
  latestAssistantMessageId,
}: CheckpointDividerProps) {
  const { plan } = usePlan(sessionId);
  const hash = useMemo(() => planHash(plan), [plan]);

  // Stamp the change synchronously during render. Safe because
  // (a) the bookkeeping is module-level, not React state — no
  // setState-cascade risk, and
  // (b) `usePlan` re-rendering the parent ChatPane fans out to every
  // divider in the same commit, so all dividers see the new stamp on
  // their first render after the plan flip.
  if (latestAssistantMessageId) {
    stampCheckpointIfChanged(sessionId, hash, latestAssistantMessageId);
  }

  const stamps = checkpointStamps.get(sessionId);
  const isCheckpoint = stamps?.has(afterMessageId) ?? false;

  if (!isCheckpoint) return null;

  return (
    <div className="my-3 mx-auto max-w-fit group">
      <Checkpoint className="gap-2">
        <span className="font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
          checkpoint
        </span>
        <CheckpointTrigger
          className="h-5 px-1.5 text-[10px] opacity-0 group-hover:opacity-100 transition-opacity"
          onClick={() => {
            console.warn("Checkpoint restore not yet wired");
          }}
          tooltip="Restore session state to this point"
        >
          <CheckpointIcon className="size-3" />
          Restore here
        </CheckpointTrigger>
      </Checkpoint>
    </div>
  );
}
