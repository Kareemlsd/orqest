"use client";

/**
 * Sources — bridge between AI Elements' citation primitives and Polymath's
 * web-search tool output.
 *
 * Two render paths, picked at call time:
 *
 *   1. **Inline citations.** When the assistant text contains numeric
 *      ref markers `[N]`, each marker is replaced with an
 *      `<InlineCitation>` whose hover-card shows the matching source's
 *      title / url / snippet. Sources are indexed by `N - 1` against
 *      the flattened, deduped web-search results.
 *
 *   2. **Collapsed tray fallback.** When text has no `[N]` markers but
 *      the turn still produced web sources, we fall back to the
 *      pre-existing `<Sources>` collapsed tray so the user can still
 *      see what the agent looked at.
 *
 * If both are present (citations *and* extra unreferenced sources) we
 * render only the inline citations — the user can still chase the
 * underlying URLs via hover, and a second tray below would feel
 * duplicative. The hidden links are not lost; they show up in the
 * citation hover when there are spare entries.
 */
import type { ReactNode } from "react";
import { Fragment } from "react";

import {
  InlineCitation,
  InlineCitationCard,
  InlineCitationCardBody,
  InlineCitationCardTrigger,
  InlineCitationSource,
  InlineCitationText,
} from "@/components/ai-elements/inline-citation";
import {
  Source,
  Sources,
  SourcesContent,
  SourcesTrigger,
} from "@/components/ai-elements/sources";

export interface WebSearchResult {
  title: string;
  url: string;
  snippet: string;
}

interface RenderResult {
  /** The text body, with `[N]` markers replaced by `<InlineCitation>`
   *  nodes when matches exist. When no markers exist the original
   *  `text` is returned untouched as a single string node. */
  textWithCitations: ReactNode;
  /** A `<Sources>` collapsed tray when no inline citations were
   *  produced but the turn still yielded web results, otherwise
   *  `null`. */
  sourcesNode: ReactNode | null;
}

const CITATION_PATTERN = /\[(\d+)\]/g;
const SNIPPET_TRUNCATE = 120;

/**
 * Walk `text` once, splitting on `[N]` patterns and folding each
 * matched marker into an `<InlineCitation>` node. Falls back to the
 * collapsed tray when no markers are found.
 */
export function renderInlineCitationsAndSources(
  text: string,
  webSearchResults: WebSearchResult[],
): RenderResult {
  if (text.length === 0) {
    return { textWithCitations: text, sourcesNode: null };
  }

  // Walk the string with `matchAll` so we can interleave inline
  // citations with the surrounding plain text without rewriting
  // markdown — the helper returns ReactNodes that get spliced into
  // ReactMarkdown output as raw children of a wrapping fragment.
  const matches = Array.from(text.matchAll(CITATION_PATTERN));

  if (matches.length === 0) {
    if (webSearchResults.length === 0) {
      return { textWithCitations: text, sourcesNode: null };
    }
    return {
      textWithCitations: text,
      sourcesNode: renderCollapsedTray(webSearchResults),
    };
  }

  const nodes: ReactNode[] = [];
  let cursor = 0;
  let nodeIdx = 0;

  for (const match of matches) {
    const start = match.index ?? 0;
    const end = start + match[0].length;
    const idx = Number.parseInt(match[1], 10) - 1;

    // Plain-text segment before this marker.
    if (start > cursor) {
      nodes.push(
        <Fragment key={`txt-${nodeIdx++}`}>{text.slice(cursor, start)}</Fragment>,
      );
    }

    const source = webSearchResults[idx];
    if (source) {
      nodes.push(renderCitation(match[1], source, nodeIdx++));
    } else {
      // Unmatched ref — keep the raw `[N]` so we don't silently lose
      // information. The agent referenced something we don't have.
      nodes.push(<Fragment key={`raw-${nodeIdx++}`}>{match[0]}</Fragment>);
    }

    cursor = end;
  }

  // Trailing tail.
  if (cursor < text.length) {
    nodes.push(<Fragment key={`txt-${nodeIdx++}`}>{text.slice(cursor)}</Fragment>);
  }

  return {
    textWithCitations: <>{nodes}</>,
    // Citations exist — suppress the duplicate tray; the hover cards
    // already expose the underlying URLs.
    sourcesNode: null,
  };
}

function renderCitation(
  marker: string,
  source: WebSearchResult,
  key: number,
): ReactNode {
  const snippet =
    source.snippet.length > SNIPPET_TRUNCATE
      ? `${source.snippet.slice(0, SNIPPET_TRUNCATE).trimEnd()}…`
      : source.snippet;

  return (
    <InlineCitation key={`cite-${key}`}>
      <InlineCitationText>
        <sup className="text-[10px] font-mono text-accent">[{marker}]</sup>
      </InlineCitationText>
      <InlineCitationCard>
        <InlineCitationCardTrigger sources={[source.url]} />
        <InlineCitationCardBody>
          <div className="p-3">
            <InlineCitationSource
              title={source.title}
              url={source.url}
              description={snippet}
            />
          </div>
        </InlineCitationCardBody>
      </InlineCitationCard>
    </InlineCitation>
  );
}

function renderCollapsedTray(results: WebSearchResult[]): ReactNode {
  return (
    <Sources>
      <SourcesTrigger count={results.length} />
      <SourcesContent>
        {results.map((s) => (
          <Source key={s.url} href={s.url} title={s.title} />
        ))}
      </SourcesContent>
    </Sources>
  );
}

/**
 * Walk the message's parts and collect every `tool-web_search`'s
 * results into one flat, deduped list (by `url`). Used by the message
 * body renderer so inline `[N]` markers can resolve their hover-card
 * payloads.
 *
 * Tolerates malformed entries silently — a tool result that's missing
 * a `url` is simply skipped rather than crashing the message render.
 */
export function collectWebSearchResults(
  parts: ReadonlyArray<unknown>,
): WebSearchResult[] {
  const seen = new Set<string>();
  const collected: WebSearchResult[] = [];

  for (const part of parts) {
    if (!part || typeof part !== "object") continue;
    const typed = part as { type?: unknown; output?: unknown };
    if (typed.type !== "tool-web_search") continue;
    const output = typed.output;
    if (!output || typeof output !== "object") continue;
    const results = (output as { results?: unknown }).results;
    if (!Array.isArray(results)) continue;
    for (const raw of results) {
      if (!raw || typeof raw !== "object") continue;
      const candidate = raw as { url?: unknown; title?: unknown; snippet?: unknown };
      const url = typeof candidate.url === "string" ? candidate.url : "";
      if (!url || seen.has(url)) continue;
      seen.add(url);
      collected.push({
        url,
        title:
          typeof candidate.title === "string" && candidate.title
            ? candidate.title
            : url,
        snippet:
          typeof candidate.snippet === "string" ? candidate.snippet : "",
      });
    }
  }

  return collected;
}
