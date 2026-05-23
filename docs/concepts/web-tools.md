# Web tools — pluggable search + fetch for autonomous agents

Autonomous Orqest agents that decide to *investigate* a question on
the open web need two reliable primitives: a ranked search, and a
content-aware page fetch. `orqest.tools.web` provides both as async
functions. No provider-specific SDK is imported in the calling code,
and the provider is selectable via environment variables so ops can
swap backends without touching agent logic.

## Providers

| Provider | Env value (`ORQEST_WEB_PROVIDER`) | API key env | Best for |
|---|---|---|---|
| Tavily | `tavily` (default) | `ORQEST_WEB_API_KEY` | General research; default |
| Exa | `exa` | same | Long-form / neural search |
| Brave Search | `brave` | same | Broad web coverage |
| Serper (Google) | `serper` | same | Google ranking |
| Disabled | `none` | — | CI / offline |

All providers are called through `httpx` — no SDK dependencies. Unknown
providers degrade gracefully: `web_search` returns an empty response
with a `disabled_reason` explaining why.

## Minimal example

```python
import asyncio

from orqest.tools.web import web_fetch, web_search


async def main() -> None:
    # Search (provider + key from env)
    resp = await web_search("k-omega SST turbulence model choice Re=1M")
    for hit in resp.results:
        print(hit.title, hit.url)

    # Fetch the top hit for deeper context
    if resp.results:
        page = await web_fetch(resp.results[0].url, max_chars=4000)
        print(page.text)


asyncio.run(main())
```

## Graceful degradation

Missing `ORQEST_WEB_API_KEY`? `web_search` returns:

```python
WebSearchResponse(
    query="...",
    results=[],
    provider="tavily",
    disabled_reason="ORQEST_WEB_API_KEY not set",
)
```

This matters for autonomous investigation tools: a `_investigate`
compound tool wraps `web_search` but must not fail when the
researcher can't reach the web. The caller sees an empty results list
with a clear reason and can fall back to memory recall or the agent's
own knowledge.

`web_fetch` does **not** require an API key — it's a plain
`follow_redirects=True` GET with a `User-Agent: orqest-web-fetch/1.0`
header. If a page is over `max_chars` the body is truncated and
`result.truncated = True`.

## Reference

::: orqest.tools.web.web_search
::: orqest.tools.web.web_fetch
