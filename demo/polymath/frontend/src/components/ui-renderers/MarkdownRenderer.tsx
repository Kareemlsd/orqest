"use client";

/**
 * MarkdownRenderer — react-markdown + remark-gfm with a copy of the
 * chat-message override (serif headings, accent links, Shiki-backed
 * fenced code, alternating-row tables).
 *
 * The override is duplicated rather than re-exported from `Message.tsx`
 * because Layer 1 work runs in parallel with other agents that may also
 * touch chat code. Once that settles, this can be lifted into a shared
 * `markdownComponents` module without behavioural change.
 */
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { BundledLanguage } from "shiki";

import {
  CodeBlock,
  CodeBlockCopyButton,
} from "@/components/ai-elements/code-block";

import { registerRenderer, type UIRenderer } from "./registry";

interface MarkdownData {
  content?: string;
}

function extractLanguage(className: string | undefined): BundledLanguage {
  if (!className) return "text" as BundledLanguage;
  const match = /language-(\w+)/.exec(className);
  return (match?.[1] ?? "text") as BundledLanguage;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const markdownComponents: Record<string, any> = {
  h1: (props: React.HTMLAttributes<HTMLHeadingElement>) => (
    <h1 className="font-serif text-[18px] mt-3 mb-2" {...props} />
  ),
  h2: (props: React.HTMLAttributes<HTMLHeadingElement>) => (
    <h2 className="font-serif text-[18px] mt-3 mb-2" {...props} />
  ),
  h3: (props: React.HTMLAttributes<HTMLHeadingElement>) => (
    <h3 className="font-serif text-[15px] mt-2 mb-1.5" {...props} />
  ),
  a: (props: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a
      className="text-accent hover:text-accent-hover no-underline"
      {...props}
    />
  ),
  code: ({
    className,
    children,
    ...props
  }: React.HTMLAttributes<HTMLElement> & { children?: React.ReactNode }) => {
    if (className && /language-\w+/.test(className)) {
      const code = String(children ?? "").replace(/\n$/, "");
      const language = extractLanguage(className);
      return (
        <CodeBlock className="my-2 text-[11px]" code={code} language={language}>
          <CodeBlockCopyButton className="absolute top-1.5 right-1.5 size-6 opacity-0 group-hover:opacity-100 transition-opacity" />
        </CodeBlock>
      );
    }
    return (
      <code
        className="bg-surface-code text-accent text-[11px] font-mono px-1.5 py-0.5 rounded-[4px]"
        {...props}
      >
        {children}
      </code>
    );
  },
  pre: ({ children, ...props }: React.HTMLAttributes<HTMLPreElement>) => {
    const child = Array.isArray(children) ? children[0] : children;
    if (
      child &&
      typeof child === "object" &&
      "props" in child &&
      (child as { props?: { className?: string } }).props?.className?.includes(
        "language-",
      )
    ) {
      return <>{children}</>;
    }
    return (
      <pre
        className="bg-surface-code border border-border-subtle rounded-md p-3 text-[11px] font-mono overflow-x-auto my-2"
        {...props}
      >
        {children}
      </pre>
    );
  },
  table: (props: React.HTMLAttributes<HTMLTableElement>) => (
    <table
      className="w-full text-[13px] my-2 [&_tr:nth-child(even)]:bg-surface-elevated/40"
      {...props}
    />
  ),
  th: (props: React.ThHTMLAttributes<HTMLTableCellElement>) => (
    <th
      className="text-left font-medium px-2 py-1 border-b border-border-subtle"
      {...props}
    />
  ),
  td: (props: React.TdHTMLAttributes<HTMLTableCellElement>) => (
    <td className="px-2 py-1 border-b border-border-subtle" {...props} />
  ),
  p: (props: React.HTMLAttributes<HTMLParagraphElement>) => (
    <p className="my-1.5 leading-relaxed" {...props} />
  ),
  ul: (props: React.HTMLAttributes<HTMLUListElement>) => (
    <ul className="list-disc pl-5 my-1.5 space-y-1" {...props} />
  ),
  ol: (props: React.OlHTMLAttributes<HTMLOListElement>) => (
    <ol className="list-decimal pl-5 my-1.5 space-y-1" {...props} />
  ),
};

const MarkdownRenderer: UIRenderer<MarkdownData> = (spec) => {
  const content = spec.data?.content ?? "";
  return (
    <div className="prose-polymath">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {content}
      </ReactMarkdown>
    </div>
  );
};

registerRenderer("markdown", MarkdownRenderer);
export default MarkdownRenderer;
