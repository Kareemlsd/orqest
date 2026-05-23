"use client";

/**
 * Composer — refactored onto AI Elements `PromptInput` primitives.
 *
 * Public API is unchanged: same props (`status` / `onSend` / `onStop`),
 * same callbacks. Internally we lean on `PromptInput`,
 * `PromptInputTextarea`, `PromptInputFooter`, `PromptInputTools`,
 * `PromptInputSubmit`.
 *
 * Polish on the editorial redesign:
 *   - Border becomes `--color-border-strong` and ships a 3px amber-subtle
 *     box-shadow ring on focus (`0 0 0 3px oklch(0.78 0.14 75 / 0.08)`).
 *   - Placeholder is now editorial — "Pick up a thread, or start a new
 *     one." instead of the prior template prose.
 *   - Footer hint is `⏎ send · ⇧⏎ newline · / commands` with each
 *     modifier wrapped in a `<Kbd>`-styled span (mono 10px, 1px border,
 *     2px 5px padding).
 *
 * Anti-slop: no avatar, no rounded-2xl, no always-on toolbar.
 */
import {
  PromptInput,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTextarea,
  PromptInputTools,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";

interface ComposerProps {
  status: "idle" | "streaming" | "submitted" | "error" | string;
  onSend: (text: string) => void;
  onStop?: () => void;
}

export function Composer({ status, onSend, onStop }: ComposerProps) {
  const isGenerating = status === "streaming" || status === "submitted";

  const handleSubmit = (message: PromptInputMessage) => {
    const text = message.text.trim();
    if (!text || isGenerating) return;
    onSend(text);
  };

  const submitStatus =
    status === "streaming" || status === "submitted" || status === "error"
      ? (status as "streaming" | "submitted" | "error")
      : "ready";

  return (
    <div
      className="px-3 py-3 bg-background"
      style={{ borderTop: "1px solid var(--color-border-subtle)" }}
    >
      <PromptInput
        // Custom focus ring per the editorial brief: 1px border that
        // strengthens to `--color-border-strong` on focus + a 3px
        // amber-subtle box-shadow ring. Tailwind v4 doesn't ship
        // utilities for our custom tokens, so arbitrary-selector
        // `focus-within` directives carry the focus state via
        // `[&:focus-within]:` literals instead of styled-jsx.
        className="rounded-md transition-colors border border-[var(--color-border-default)] [&:focus-within]:border-[var(--color-border-strong)] [&:focus-within]:shadow-[0_0_0_3px_oklch(0.78_0.14_75_/_0.08)]"
        onSubmit={handleSubmit}
        style={{ background: "var(--color-surface-elevated)" }}
      >
        <PromptInputTextarea
          className="bg-transparent text-[14px] leading-6 placeholder:text-muted-foreground border-0 shadow-none px-3 py-2 max-h-48 min-h-10"
          placeholder="Pick up a thread, or start a new one."
        />
        <PromptInputFooter>
          <PromptInputTools className="font-mono text-[10px] text-muted-foreground px-1 flex items-center gap-3">
            <span className="inline-flex items-center gap-1.5">
              <KbdHint>{"⏎"}</KbdHint>
              <span className="uppercase tracking-wide">send</span>
            </span>
            <span className="inline-flex items-center gap-1.5">
              <KbdHint>{"⇧⏎"}</KbdHint>
              <span className="uppercase tracking-wide">newline</span>
            </span>
            <span className="inline-flex items-center gap-1.5">
              <KbdHint>/</KbdHint>
              <span className="uppercase tracking-wide">commands</span>
            </span>
          </PromptInputTools>
          <PromptInputSubmit
            className="size-7"
            onStop={onStop}
            status={submitStatus}
          />
        </PromptInputFooter>
      </PromptInput>
    </div>
  );
}

/**
 * Inline keycap chip — mono 10px, 1px border, 2px 5px padding. Mirror
 * of the design's `<Kbd>` primitive.
 */
function KbdHint({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="inline-flex items-center font-mono text-[10px] leading-none rounded-sm"
      style={{
        padding: "2px 5px",
        border: "1px solid var(--color-border-default)",
        color: "var(--color-foreground)",
        background: "rgba(255,255,255,0.02)",
      }}
    >
      {children}
    </span>
  );
}
