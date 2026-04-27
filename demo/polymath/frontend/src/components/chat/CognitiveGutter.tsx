"use client";

/**
 * CognitiveGutter — the through-line for assistant turns.
 *
 * A 24px-wide left rail that runs alongside each assistant message body.
 * Encodes three orthogonal signals in a single column of pixels:
 *
 *   1. Spine: faint hairline that anchors the turn. Always rendered.
 *   2. Confidence bar: top-anchored fill, height proportional to the
 *      agent's self-rated confidence, color stepped through four
 *      stops (high / mid / low / doubt). Suppressed when confidence
 *      is `null` (the agent didn't return an `EnrichedOutput`).
 *   3. Event ticks: per-event marks at fractional vertical positions
 *      `(at: 0..1)`. Tool ticks are 6×6 squares; memory dots are 5×5
 *      circles; sub-agent ticks are 6×6 squares in the semantic kind
 *      color; thought ticks are 6×6 squares in amber.
 *   4. Live indicator: when `live={true}`, an amber dot pinned at the
 *      bottom with a 3px amber-subtle box-shadow pulse.
 *
 * Replaces the prior `<ConfidenceBadge>` row above the assistant
 * header — confidence is now spatial (height-encoded) instead of
 * numeric (label-encoded), freeing the header for the editorial
 * `POLYMATH · TURN NN  ·  HH:MM:SS  ·  tools` masthead.
 *
 * Anti-slop discipline: no animations beyond the `live` pulse, no
 * iconography, no labels — the gutter speaks through proportion and
 * placement. Tooltips on each tick carry the only prose.
 */
import { memo } from "react";

export type CognitiveEventKind = "tool" | "memory" | "sub" | "thought";

export interface CognitiveEvent {
  /** Vertical position in `0..1`. `0` = top of body, `1` = bottom. */
  at: number;
  kind: CognitiveEventKind;
  /** Optional hover label. Surfaces as the native `title` tooltip. */
  label?: string;
}

export interface CognitiveGutterProps {
  /** 0..1 — drives both the bar's height and color tier. `null` means
   *  no confidence frame was captured for this turn (e.g. the tool
   *  call didn't return an `EnrichedOutput`). When null, the bar is
   *  suppressed but the spine + ticks still render. */
  confidence?: number | null;
  events?: ReadonlyArray<CognitiveEvent>;
  /** When true, an amber pulse pins to the bottom of the spine —
   *  signals "the agent is still thinking on this turn". */
  live?: boolean;
}

/**
 * Map a confidence score to one of the four design-token stops.
 * Thresholds match the design spec (`≥0.85` / `≥0.65` / `≥0.45` / else).
 */
function confidenceColor(confidence: number): string {
  if (confidence >= 0.85) return "var(--color-conf-high)";
  if (confidence >= 0.65) return "var(--color-conf-mid)";
  if (confidence >= 0.45) return "var(--color-conf-low)";
  return "var(--color-conf-doubt)";
}

function eventVisualStyle(kind: CognitiveEventKind): React.CSSProperties {
  switch (kind) {
    case "memory":
      // 5×5 circle in episodic violet; no ring.
      return {
        width: 5,
        height: 5,
        borderRadius: "50%",
        background: "var(--color-kind-episodic)",
      };
    case "sub":
      // 6×6 square in semantic cyan; thin ring against the page.
      return {
        width: 6,
        height: 6,
        borderRadius: 1,
        background: "var(--color-kind-semantic)",
        border: "1px solid var(--color-background)",
      };
    case "thought":
      // 6×6 square in amber accent; thin ring.
      return {
        width: 6,
        height: 6,
        borderRadius: 1,
        background: "var(--color-accent)",
        border: "1px solid var(--color-background)",
      };
    case "tool":
    default:
      // 6×6 square in muted-foreground; thin ring against the page.
      return {
        width: 6,
        height: 6,
        borderRadius: 1,
        background: "var(--color-muted-foreground)",
        border: "1px solid var(--color-background)",
      };
  }
}

function CognitiveGutterImpl({
  confidence = null,
  events = [],
  live = false,
}: CognitiveGutterProps) {
  // Clamp the bar to ≥6% so even very low confidence shows a sliver
  // of color rather than vanishing. The numeric value still encodes
  // the actual score in `confidenceColor()` below.
  const hasConfidence = typeof confidence === "number" && confidence !== null;
  const pct = hasConfidence ? Math.max(0.06, confidence as number) : 0;
  const tone = hasConfidence ? confidenceColor(confidence as number) : "transparent";

  return (
    <div
      style={{
        width: 24,
        position: "relative",
        flexShrink: 0,
        alignSelf: "stretch",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        paddingTop: 4,
      }}
      aria-hidden
    >
      {/* spine — always rendered; the through-line for the turn */}
      <div
        style={{
          position: "absolute",
          top: 6,
          bottom: 6,
          left: "50%",
          width: 1,
          background: "var(--color-border-subtle)",
        }}
      />
      {/* confidence bar — drawn over the spine */}
      {hasConfidence && (
        <div
          style={{
            position: "absolute",
            top: 6,
            left: "50%",
            width: 1,
            height: `calc((100% - 12px) * ${pct})`,
            background: tone,
            transform: "translateX(-0.5px)",
          }}
        />
      )}
      {/* event ticks */}
      {events.map((e, i) => (
        <div
          key={i}
          title={e.label}
          style={{
            position: "absolute",
            top: `calc(6px + (100% - 12px) * ${e.at})`,
            left: "50%",
            transform: "translate(-50%, -50%)",
          }}
        >
          <div style={eventVisualStyle(e.kind)} />
        </div>
      ))}
      {/* live indicator */}
      {live && (
        <div
          style={{
            position: "absolute",
            bottom: 4,
            left: "50%",
            transform: "translateX(-50%)",
            width: 5,
            height: 5,
            borderRadius: "50%",
            background: "var(--color-accent)",
            boxShadow: "0 0 0 3px var(--color-accent-subtle)",
          }}
        />
      )}
    </div>
  );
}

/**
 * Memoised export — the gutter re-renders on every confidence/events
 * change, but with stable props it sits idle. Stream B ensures the
 * `events` array is `useMemo`-stabilised upstream so reference equality
 * holds across token ticks.
 */
export const CognitiveGutter = memo(CognitiveGutterImpl);
CognitiveGutter.displayName = "CognitiveGutter";
