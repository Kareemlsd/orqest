"""PDF / paper extraction tool — pulls structured text from arxiv papers + PDFs.

Two extraction paths, tried in order:

1. **ArXiv HTML version** (preferred when available) — single-column,
   equations rendered as MathML, references linked. Cleaner LLM input
   than PDF text extraction. Fetched from ``https://arxiv.org/html/<id>``.

2. **PDF text extraction** via ``pypdf`` (fallback) — works for any PDF URL
   or local path. Equations and tables degrade ungracefully; sufficient for
   abstracts + section text but expect noise.

Returns structured JSON: ``{title?, sections: [{heading, content}], references?,
raw_text, total_chars, truncated, source}``.

Equations and figures are NOT processed by this tool — for slice 1 the agent
sees flat text. Better extraction (LaTeX preservation, figure captions
matched to images) is a slice-2 polish item.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
from html.parser import HTMLParser
from typing import Annotated

import httpx
import pypdf
from pydantic_ai import RunContext
from pydantic_ai.tools import Tool

from polymath.runtime import emit
from polymath.state import PolymathState
from polymath.tools.arxiv import _normalise_arxiv_id


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------

_DEFAULT_MAX_CHARS = 80_000
"""Hard cap on returned text. Papers up to ~80KB pass through; longer ones
truncate with a notice. The agent's context handles ~80K comfortably; bigger
chunks push other context out."""

_SECTION_HEADING_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*\.?\s+|"          # numbered: '3.', '3.1', '3.1.2'
    r"(?:Abstract|Introduction|Background|Related Work|Method[s]?|"
    r"Approach|Experiments?|Results?|Discussion|Conclusion[s]?|"
    r"References|Appendix|Acknowledg[e]?ments?)\b)"
    r".{0,80}$",
    re.MULTILINE | re.IGNORECASE,
)


class _HTMLToText(HTMLParser):
    """Minimal HTML→text stripper for arxiv's HTML version.

    Drops <script>, <style>, <math>-as-mathml-text (kept as raw symbols), and
    preserves headings + paragraph breaks. Sufficient for LLM consumption;
    not a full DOM model.
    """

    _SKIP_TAGS = {"script", "style"}
    _BLOCK_TAGS = {
        "p", "div", "section", "article", "li", "br", "hr", "header", "footer",
        "h1", "h2", "h3", "h4", "h5", "h6",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:  # noqa: ARG002
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS:
            self._chunks.append("\n")
            if tag.startswith("h") and len(tag) == 2:
                # Mark headings with a newline + form-feed so we can re-detect them
                self._chunks.append("\n## ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        # Collapse excess whitespace but preserve paragraph breaks
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n\s*\n\s*\n+", "\n\n", raw)
        return raw.strip()


def _split_into_sections(text: str) -> list[dict]:
    """Heuristic section split.

    Walks the text, finds lines that look like section headings, slices the
    text between them. Falls back to a single 'body' section if no headings
    detected.
    """
    matches = list(_SECTION_HEADING_RE.finditer(text))
    if not matches:
        return [{"heading": "body", "content": text.strip()}]

    sections: list[dict] = []
    # Preamble before the first heading (often the title block or abstract).
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()].strip()
        if preamble:
            sections.append({"heading": "preamble", "content": preamble})

    for i, m in enumerate(matches):
        heading = m.group(0).strip().lstrip("#").strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if content:
            sections.append({"heading": heading[:120], "content": content})
    return sections


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    """Return (possibly-truncated text, was_truncated)."""
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "\n\n[... TRUNCATED ...]", True


# ---------------------------------------------------------------------------
# Extraction paths
# ---------------------------------------------------------------------------

async def _try_arxiv_html(arxiv_id: str, max_chars: int) -> dict | None:
    """Try the HTML version. Returns extraction dict on success, None on failure."""
    url = f"https://arxiv.org/html/{arxiv_id}"
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return None
        # Arxiv returns a stub HTML page (no real content) when the HTML
        # version doesn't exist; detect by size.
        if len(resp.text) < 2_000:
            return None
        parser = _HTMLToText()
        parser.feed(resp.text)
        text = parser.text()
        if len(text) < 500:
            return None
        truncated_text, was_truncated = _truncate(text, max_chars)
        sections = _split_into_sections(truncated_text)
        # Title is the first non-empty line of the preamble usually.
        title = None
        if sections and sections[0]["heading"] == "preamble":
            first_line = sections[0]["content"].split("\n", 1)[0].strip()
            if 5 < len(first_line) < 250:
                title = first_line
        return {
            "source": "arxiv_html",
            "url": url,
            "title": title,
            "sections": sections,
            "total_chars": len(text),
            "truncated": was_truncated,
            "raw_text": truncated_text,
        }
    except Exception:  # noqa: BLE001
        return None


async def _try_pdf(url_or_path: str, max_chars: int) -> dict:
    """PDF text extraction via pypdf. Raises on failure (caller wraps)."""
    is_url = url_or_path.startswith(("http://", "https://"))
    if is_url:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            resp = await client.get(url_or_path)
            resp.raise_for_status()
            pdf_bytes = resp.content
        source_url: str | None = url_or_path
    else:
        # Local filesystem path (sandbox-relative; the agent's sandbox tooling
        # would have handled this differently in production, but slice 1 stays
        # URL-driven)
        with open(url_or_path, "rb") as f:
            pdf_bytes = f.read()
        source_url = None

    def _extract() -> tuple[str, str | None]:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        title = None
        if reader.metadata and reader.metadata.title:
            title = str(reader.metadata.title).strip()
        return "\n\n".join(pages), title

    text, title = await asyncio.to_thread(_extract)
    truncated_text, was_truncated = _truncate(text, max_chars)
    sections = _split_into_sections(truncated_text)
    return {
        "source": "pdf",
        "url": source_url,
        "title": title,
        "sections": sections,
        "total_chars": len(text),
        "truncated": was_truncated,
        "raw_text": truncated_text,
    }


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

async def _pdf_extract(
    ctx: RunContext[PolymathState],
    source: Annotated[
        str,
        "ArXiv ID (e.g. '2405.12345'), arxiv URL, full PDF URL, or sandbox path. "
        "ArXiv inputs prefer the HTML version (cleaner) and fall back to PDF.",
    ],
    max_chars: Annotated[
        int,
        "Truncate extracted text at this many chars (default 80000). Bigger papers get a [... TRUNCATED ...] tail.",
    ] = _DEFAULT_MAX_CHARS,
) -> str:
    """Extract structured text from a paper. Returns JSON with sections, title, total chars, and source path used."""
    sid = ctx.deps.session_id
    await emit(sid, "tool.pdf_extract.started", {"source": source})

    try:
        # Path 1: arxiv-shaped input — try HTML first.
        normalised = _normalise_arxiv_id(source)
        is_arxiv = bool(re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", normalised))
        result: dict | None = None

        if is_arxiv:
            result = await _try_arxiv_html(normalised, max_chars)
            if result is None:
                # HTML failed; fall back to PDF via arxiv pdf url
                pdf_url = f"https://arxiv.org/pdf/{normalised}.pdf"
                result = await _try_pdf(pdf_url, max_chars)
        else:
            # Path 2: explicit URL or path — PDF extraction
            result = await _try_pdf(source, max_chars)
    except Exception as exc:  # noqa: BLE001
        await emit(
            sid,
            "tool.pdf_extract.error",
            {"source": source, "error": str(exc)},
        )
        return json.dumps({"error": f"pdf_extract failed: {type(exc).__name__}: {exc}"})

    await emit(
        sid,
        "tool.pdf_extract.completed",
        {
            "source": source,
            "extracted_source": result["source"],
            "n_sections": len(result["sections"]),
            "total_chars": result["total_chars"],
            "truncated": result["truncated"],
        },
    )
    return json.dumps(result, ensure_ascii=False)


pdf_extract = Tool(_pdf_extract, name="pdf_extract")
