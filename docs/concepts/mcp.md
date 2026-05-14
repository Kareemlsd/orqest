# MCP — Model Context Protocol

Orqest is both an **MCP client** (consume external tools from MCP servers) and an **MCP server** (expose Orqest's autonomy primitives — `create_agent`, `run_agent`, `solve_goal` — to Claude Desktop, Cursor, or any other MCP client). It also ships **auto-discovery**: when a tool is missing at runtime, Orqest can search MCP for a server advertising the capability, gate the request through a `PermissionGate`, and register the discovered tools transparently.

## What problem does this solve?

MCP is the de-facto protocol for tool interoperability. An agent that integrates only with hand-coded tools is sealed off from the broader ecosystem; an agent that integrates with MCP can use any MCP-compliant capability without re-coding. Orqest wraps the MCP wire format in pydantic-ai-shaped Tool instances, so MCP capabilities slot into your existing agent runs with zero translation. Auto-discovery closes the last mile: when an LLM hallucinates a tool name, instead of failing, the framework finds and registers a real one — gated by an explicit security boundary.

## The five primitives

| Primitive | Role |
|-----------|------|
| `MCPServerManager` | Client — manage connections to multiple MCP servers |
| `MCPToolAdapter` | Bridge — adapt MCP tool definitions into pydantic-ai `Tool` instances |
| `MCPDiscovery` | Search — find MCP servers that advertise a capability |
| `DiscoveryHook` | Opportunistic — auto-discover on "tool not found" errors |
| `PermissionGate` | Security boundary — gates which tool names may be auto-registered |

Plus `create_orqest_server` for exposing Orqest itself as an MCP server.

## MCPServerManager — client

The lifecycle owner. Connects to multiple MCP servers, exposes their tools as a flat list of pydantic-ai `Tool` instances.

```python
import asyncio
from orqest.mcp import MCPConfig, MCPServerConfig, MCPServerManager


async def main():
    config = MCPConfig(
        servers=[
            MCPServerConfig(
                name="filesystem",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp/sandbox"],
            ),
            MCPServerConfig(
                name="github",
                command="npx",
                args=["-y", "@modelcontextprotocol/server-github"],
                env={"GITHUB_TOKEN": "ghp_..."},
            ),
        ],
    )

    async with MCPServerManager(config) as manager:
        tools = manager.get_all_tools()             # list[pydantic_ai.Tool]
        # Pass to your agent
        agent = MyAgent(..., tools=tools)
        await agent.run(state)


asyncio.run(main())
```

`MCPServerManager` is an async context manager. On `__aenter__` it `connect_all()`s each server; on `__aexit__` it disconnects cleanly.

For single-server access without the multi-server manager:

```python
from orqest.mcp import MCPConnection, MCPServerConfig

async with MCPConnection(MCPServerConfig(name="fs", command="...", args=[...])) as conn:
    for tool in conn.tools:
        ...
```

## MCPToolAdapter — bridging

Converts MCP tool definitions to pydantic-ai `Tool` instances. The adapter wraps the tool callable in graceful error-string return semantics — when the underlying MCP server raises, the agent sees a string error rather than a crash.

```python
from orqest.mcp import MCPToolAdapter

adapter = MCPToolAdapter(connection)
tool = adapter.adapt(mcp_tool_def)              # single tool
tools = adapter.adapt_many(connection.tools)    # batch
```

In practice, `MCPServerManager.get_all_tools()` already does the adaptation — you rarely call the adapter directly.

## MCPDiscovery — search

Finds MCP servers that advertise a given capability. Composes three sources:

1. **Online registry** — known MCP server registry (well-known endpoints)
2. **Well-known manifests** — servers advertising themselves at well-known URLs
3. **Web fallback** — search-engine-driven discovery for less common capabilities

```python
from orqest.mcp import MCPDiscovery

discovery = MCPDiscovery()
results = await discovery.search("compute_p95_latency", max_results=5)
for server in results:
    print(f"{server.name}: {server.command} {server.args}")
```

Results are `DiscoveredServer` records — enough metadata to instantiate an `MCPServerConfig` and connect.

## PermissionGate — the security boundary

A remote MCP server is a code-execution surface. Auto-registering a tool from an arbitrary server is a security risk. The gate is the explicit "yes" boundary, default-deny.

```python
from orqest.mcp import AllowAll, AllowList, DenyAll

# Deny every discovery (default)
gate = DenyAll()

# Permit any tool name — DEVELOPMENT ONLY
gate = AllowAll()

# Production: regex allowlist (re.search semantics; anchor with ^…$ for full match)
gate = AllowList([
    r"^web\.",                # web.search, web.fetch
    r"^fs\.",                 # fs.read, fs.write
    r"^compute_p\d+_latency",
])
```

`PermissionGate` is a Protocol — you can plug in your own gate (per-user, per-tenant, time-bounded, audit-logged) by implementing `async def allow(self, tool_name: str) -> bool`.

## Auto-discovery — two integration paths

### Deliberate: `ToolRegistry.get_or_discover`

Called by code that knows it needs a tool *right now*. Common pattern: tool resolution at agent-spawn time.

```python
from orqest.autonomy import ToolRegistry
from orqest.mcp import MCPDiscovery, MCPServerManager, AllowList

registry = ToolRegistry()

tool = await registry.get_or_discover(
    "compute_p95_latency",
    discovery=MCPDiscovery(),
    manager=MCPServerManager(MCPConfig(servers=[])),
    permission=AllowList([r"^compute_"]),
    audit_bus=workbench.event_bus,
    max_servers=3,
)
```

Returns the registered `Tool` on hit, `None` on miss. The gate is consulted before any network call.

### Opportunistic: `DiscoveryHook`

Catches runtime "tool not found" errors raised by hallucinating LLMs and recovers via discovery. Wire on a `HookRunner`.

```python
from orqest.mcp import DiscoveryHook, AllowList

hook = DiscoveryHook(
    registry=registry,
    discovery=MCPDiscovery(),
    manager=manager,
    permission=AllowList([r"^web\.", r"^fs\."]),
    audit_bus=workbench.event_bus,
)

runner = HookRunner(hooks=[hook])
# Pass runner to your CompoundTool / SubAgentTool / agent
```

When an LLM fabricates a tool call to `web.scrape_table` (which doesn't exist locally), `DiscoveryHook.on_error` fires:

1. Detects "tool not found" pattern in the error message
2. Asks `MCPDiscovery` to search for `web.scrape_table`
3. Gate consulted — `AllowList` matches `^web\.`, permits
4. `MCPServerManager` connects, `MCPToolAdapter` adapts, `ToolRegistry` registers
5. Returns `Redirect(new_tool="web.scrape_table")` — the caller retries with the now-registered tool

If the gate denies, discovery fails, or the error wasn't a tool-not-found, returns `Continue()` (no recovery).

## Audit events

All discovery flows emit typed events on the `EventBus` when an `audit_bus` is provided:

| Event | When |
|-------|------|
| `discovery.requested` | A missing tool triggered discovery |
| `discovery.connected` | A discovered tool was registered (one per tool) |
| `discovery.denied` | `PermissionGate` rejected the request |
| `discovery.failed` | Discovery succeeded conceptually but registration failed |

These flow through the same bus the rest of the cognitive substrate uses — subscribe handlers that forward to your existing observability layer (structlog / OpenTelemetry / etc.).

## Orqest as an MCP server

`create_orqest_server` exposes Orqest itself as a FastMCP server. The exposed tools:

- `create_agent(spec_json)` — accept an `AgentSpec` and instantiate a `DynamicAgent`
- `run_agent(name, input)` — invoke a previously-created agent
- `solve_goal(goal)` — run the `MetaOrchestrator`
- `list_agents()` — enumerate the registered roster

```python
from orqest.autonomy import AgentFactory, MetaOrchestrator, ToolRegistry
from orqest.mcp import create_orqest_server

registry = ToolRegistry()
factory = AgentFactory(registry=registry, default_model="openai:gpt-4.1", api_key="sk-...")
meta = MetaOrchestrator(planner=..., factory=factory, registry=registry)

server = create_orqest_server(
    factory=factory,
    registry=registry,
    meta=meta,
    default_model="openai:gpt-4.1",
    api_key="sk-...",
)

# Run as a FastMCP server (stdio transport for Claude Desktop / Cursor)
# python -m orqest.mcp.server
```

Mount in Claude Desktop / Cursor by adding to the MCP config:

```json
{
  "mcpServers": {
    "orqest": {
      "command": "python",
      "args": ["-m", "orqest.mcp.server"]
    }
  }
}
```

Auto-discovery scans the standard config locations: `~/.claude.json`, `~/.claude/claude.json`, `~/.config/Claude/claude_desktop_config.json`.

## Best practices

- **Default `PermissionGate.DenyAll`.** Auto-discovery is off by default; consumers opt in with `AllowList(...)` or `AllowAll()` for dev. Don't ship `AllowAll` in production.
- **Anchor regex patterns.** `re.search` semantics means `r"web"` matches `web.fetch` AND `cobwebs.compute`. Anchor with `^...$` (or at least `^...`).
- **Audit everything.** Pass `audit_bus=workbench.event_bus` so denied/failed discoveries surface in your logs. Silent denials are the worst kind of bug.
- **Use the deliberate path when you can.** `ToolRegistry.get_or_discover` is the predictable path; `DiscoveryHook` is the safety net for hallucinations. Don't lean on the safety net as a primary discovery strategy.
- **`MCPServerManager` is a context manager.** Use `async with`; don't call `connect_all`/`disconnect` manually unless you have a reason.

## Pitfalls

- **Don't expose Orqest as an MCP server with `AllowAll` on the consumer side.** That's a "remote code execution as a service" configuration. Pair `create_orqest_server` with proper auth on the transport.
- **Don't share `MCPServerManager` across processes.** Each connection holds OS-level handles; cross-process sharing breaks cleanup semantics.
- **Don't trust the tool description from a discovered MCP server.** The `description` is what the LLM reads to decide whether to call the tool — a malicious server can advertise misleading descriptions. Combine `PermissionGate` with name-based allowlisting; consider description-validation hooks for high-trust deployments.
- **Don't auto-register dynamic-discovery into the *spawned-agent* roster.** A `DynamicAgent` spawned by the orchestrator should reference tools from the *static* registry the consumer wired; allowing every `DynamicAgent` to discover at will defeats the audit trail. Discovery is a registry-level decision, not a per-agent one.

## What's happening under the hood

1. `MCPServerManager.connect_all()` spawns each server's transport (stdio subprocess or HTTP), establishes the MCP handshake, and inventories tools
2. `MCPToolAdapter.adapt[_many]` wraps each MCP tool's `call` in a coroutine that catches `MCPError` and returns a string-shaped error result (preserves agent flow)
3. `ToolRegistry.get_or_discover` on miss: emit `discovery.requested`, search via `MCPDiscovery`, gate via `PermissionGate.allow`, connect via `MCPServerManager`, adapt + register, emit `discovery.connected` per tool
4. `DiscoveryHook.on_error` short-circuits to `Continue` unless the error matches a "tool not found" string fragment; otherwise routes to the same registry path as the deliberate flow
5. `create_orqest_server` builds a FastMCP server whose tools are bound to the supplied `factory`/`registry`/`meta`; FastMCP handles the JSON-RPC wire format

## Related Concepts

- [Autonomy](autonomy.md) — `ToolRegistry` is the substrate MCP integrates with
- [Hooks & Lifecycle](hooks-and-lifecycle.md) — `DiscoveryHook` returns `HookDecision`s through `HookRunner`
- [Self-Healing](healing.md) — `DiscoverAndRetry` recovery action triggers the discovery flow
- [Observability](observability.md) — `discovery.*` audit events flow on the `EventBus`
