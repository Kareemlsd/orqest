"use client";

/**
 * Shared empty-tab layout. Single serif sentence + mono caption, left-
 * aligned at 30% viewport per design-aesthetic.md + ref 10 empty-state.
 */
interface TabStubProps {
  title: string;
  caption: string;
}

export function TabStub({ title, caption }: TabStubProps) {
  return (
    <div className="h-full flex flex-col items-start justify-start pt-[30vh] pl-12 pr-6">
      <h2 className="font-serif text-[24px] text-foreground leading-tight">
        {title} <span className="text-muted-foreground">— {caption}</span>
      </h2>
      <p className="mt-2 font-mono text-[11px] text-muted-foreground">
        stub · wired in a later phase
      </p>
    </div>
  );
}
