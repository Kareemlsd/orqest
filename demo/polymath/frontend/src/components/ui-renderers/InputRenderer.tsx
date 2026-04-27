"use client";

/**
 * InputRenderer — covers the standard HTML input families: text,
 * textarea, number, range, select (single / multi), checkbox, radio,
 * date, time, email, url, file.
 *
 * Each input fires `ctx.emitEvent(event_name, { ...event_payload, name,
 * value })` on change. Text and textarea changes are debounced ~250ms
 * to avoid flooding the backend with one event per keystroke. Other
 * input types fire immediately because they're discrete events
 * (clicking a checkbox, picking a date) where the user expects an
 * instant round-trip.
 *
 * `kind` enumerates the supported variants. Unknown kinds fall through
 * to a single-line text input — keeps the renderer forward-compatible
 * if the backend grows new input kinds before the frontend catches up.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

import { registerRenderer, type RenderContext, type UIRenderer } from "./registry";

interface InputOption {
  value: string;
  label?: string;
}

interface InputData {
  kind?:
    | "text"
    | "textarea"
    | "number"
    | "range"
    | "select"
    | "multi-select"
    | "checkbox"
    | "radio"
    | "date"
    | "time"
    | "email"
    | "url"
    | "file";
  name?: string;
  label?: string;
  default?: unknown;
  placeholder?: string;
  event_name?: string;
  event_payload?: Record<string, unknown>;
  min?: number;
  max?: number;
  step?: number;
  rows?: number;
  accept?: string;
  options?: InputOption[];
  required?: boolean;
}

const BASE_INPUT =
  "w-full rounded-md border border-border-default bg-surface-card px-2.5 py-1.5 font-mono text-[12px] " +
  "text-foreground placeholder:text-muted-foreground/70 " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:border-accent";

const TEXT_DEBOUNCE_MS = 250;

const InputRenderer: UIRenderer<InputData> = (spec, ctx) => {
  return <InputImpl spec={spec} ctx={ctx} />;
};

function InputImpl({
  spec,
  ctx,
}: {
  spec: { component_id: string; data?: InputData };
  ctx: RenderContext;
}) {
  const data = spec.data ?? {};
  const kind = data.kind ?? "text";
  const name = data.name ?? spec.component_id;
  const label = data.label ?? "";

  const emit = useCallback(
    (value: unknown) => {
      if (!data.event_name) return;
      void ctx.emitEvent(data.event_name, {
        ...(data.event_payload ?? {}),
        name,
        value,
      });
    },
    [ctx, data.event_name, data.event_payload, name],
  );

  const wrapper = (children: React.ReactNode) => (
    <label className="flex flex-col gap-1 w-full">
      {label && (
        <span className="font-mono text-[11px] text-muted-foreground">
          {label}
        </span>
      )}
      {children}
    </label>
  );

  if (kind === "textarea") {
    return wrapper(
      <DebouncedTextInput
        as="textarea"
        rows={data.rows ?? 4}
        placeholder={data.placeholder}
        defaultValue={typeof data.default === "string" ? data.default : ""}
        onCommit={emit}
      />,
    );
  }

  if (kind === "number" || kind === "range") {
    const initial = typeof data.default === "number" ? data.default : "";
    return wrapper(
      <input
        type={kind === "range" ? "range" : "number"}
        name={name}
        defaultValue={initial}
        min={data.min}
        max={data.max}
        step={data.step}
        onChange={(e) => {
          const raw = e.target.value;
          const num = raw === "" ? null : Number(raw);
          emit(num);
        }}
        className={cn(BASE_INPUT, kind === "range" && "px-0")}
      />,
    );
  }

  if (kind === "select") {
    const initial =
      typeof data.default === "string" || typeof data.default === "number"
        ? String(data.default)
        : "";
    return wrapper(
      <select
        name={name}
        defaultValue={initial}
        onChange={(e) => emit(e.target.value)}
        className={BASE_INPUT}
      >
        {(data.options ?? []).map((opt, idx) => (
          <option key={`${opt.value}-${idx}`} value={opt.value}>
            {opt.label ?? opt.value}
          </option>
        ))}
      </select>,
    );
  }

  if (kind === "multi-select") {
    const initial = Array.isArray(data.default)
      ? data.default.map((v) => String(v))
      : [];
    return wrapper(
      <select
        name={name}
        multiple
        defaultValue={initial}
        onChange={(e) => {
          const values = Array.from(e.target.selectedOptions).map(
            (opt) => opt.value,
          );
          emit(values);
        }}
        className={cn(BASE_INPUT, "min-h-24")}
      >
        {(data.options ?? []).map((opt, idx) => (
          <option key={`${opt.value}-${idx}`} value={opt.value}>
            {opt.label ?? opt.value}
          </option>
        ))}
      </select>,
    );
  }

  if (kind === "checkbox") {
    const initial = data.default === true;
    return (
      <label className="inline-flex items-center gap-2">
        <input
          type="checkbox"
          name={name}
          defaultChecked={initial}
          onChange={(e) => emit(e.target.checked)}
          className="h-3.5 w-3.5 accent-[var(--color-accent)]"
        />
        {label && (
          <span className="font-mono text-[12px] text-foreground">{label}</span>
        )}
      </label>
    );
  }

  if (kind === "radio") {
    const initial =
      typeof data.default === "string" ? data.default : undefined;
    return wrapper(
      <div className="flex flex-col gap-1">
        {(data.options ?? []).map((opt, idx) => (
          <label
            key={`${opt.value}-${idx}`}
            className="inline-flex items-center gap-2"
          >
            <input
              type="radio"
              name={name}
              value={opt.value}
              defaultChecked={initial === opt.value}
              onChange={(e) => emit(e.target.value)}
              className="h-3.5 w-3.5 accent-[var(--color-accent)]"
            />
            <span className="font-mono text-[12px]">{opt.label ?? opt.value}</span>
          </label>
        ))}
      </div>,
    );
  }

  if (kind === "file") {
    return wrapper(
      <input
        type="file"
        name={name}
        accept={data.accept}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (!file) {
            emit(null);
            return;
          }
          // Surface the metadata; the actual upload would need an
          // out-of-band POST that the agent's event handler can trigger.
          emit({ name: file.name, size: file.size, type: file.type });
        }}
        className={cn(BASE_INPUT, "py-1")}
      />,
    );
  }

  // Default: standard single-line input. Includes date / time / email /
  // url and the fallthrough for unknown `kind`.
  const inputType =
    kind === "date" || kind === "time" || kind === "email" || kind === "url"
      ? kind
      : "text";

  if (inputType === "text") {
    return wrapper(
      <DebouncedTextInput
        as="input"
        placeholder={data.placeholder}
        defaultValue={typeof data.default === "string" ? data.default : ""}
        onCommit={emit}
      />,
    );
  }

  return wrapper(
    <input
      type={inputType}
      name={name}
      defaultValue={typeof data.default === "string" ? data.default : ""}
      placeholder={data.placeholder}
      onChange={(e) => emit(e.target.value)}
      className={BASE_INPUT}
    />,
  );
}

interface DebouncedTextInputProps {
  as: "input" | "textarea";
  defaultValue: string;
  placeholder?: string;
  rows?: number;
  onCommit: (value: string) => void;
}

function DebouncedTextInput({
  as,
  defaultValue,
  placeholder,
  rows,
  onCommit,
}: DebouncedTextInputProps) {
  const [value, setValue] = useState(defaultValue);
  const timerRef = useRef<number | null>(null);
  const onCommitRef = useRef(onCommit);
  onCommitRef.current = onCommit;

  // Flush any pending debounce on unmount so a fast-moving user doesn't
  // lose their last edit when the input is hot-swapped.
  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        onCommitRef.current(value);
      }
    };
    // Intentionally empty: we only want to fire the cleanup on unmount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onChange = (next: string) => {
    setValue(next);
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
    }
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      onCommitRef.current(next);
    }, TEXT_DEBOUNCE_MS);
  };

  if (as === "textarea") {
    return (
      <textarea
        value={value}
        rows={rows}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className={cn(BASE_INPUT, "resize-y leading-relaxed")}
      />
    );
  }
  return (
    <input
      type="text"
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className={BASE_INPUT}
    />
  );
}

registerRenderer("input", InputRenderer);
export default InputRenderer;
