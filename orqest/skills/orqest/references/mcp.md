# MCP — reference

Compressed judgment layer over `orqest/mcp/`. For full reference, read `docs/concepts/mcp.md`.

## Orqest's MCP role — both sides of the wire

| Role | Primitive | Use |
|---|---|---|
| **Client** | `MCPServerManager` | Connect to external MCP servers; consume their tools |
| **Server** | `create_orqest_server` | Expose Orqest's autonomy primitives (`create_agent`, `run_agent`, `solve_goal`) over MCP |
| **Discovery** | `MCPDiscovery` + `ToolRegistry.get_or_discover` + `DiscoveryHook` | Find + register MCP tools at runtime when an LLM needs one |

## Client wire-up — `MCPServerManager`

Async context manager. Connects on `__aenter__`, disconnects cleanly on `__aexit__`.

```python
from orqest.mcp import MCPConfig, MCPServerConfig, MCPServerManager

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
    tools = manager.get_all_tools()                          # → list[pydantic_ai.Tool]
    # Pass to your agent
    agent = MyAgent(tools=tools, ...)
    await agent.run(state)
```

Single-server variant:

```python
from orqest.mcp import MCPConnection

async with MCPConnection(MCPServerConfig(name="fs", ...)) as conn:
    for tool in conn.tools:
        ...
```

The MCP tool callables are wrapped (by `MCPToolAdapter`) in graceful error-string return semantics — when the underlying MCP server raises, the agent sees a string error rather than a crash.

## `PermissionGate` — security boundary

Remote MCP servers are code-execution surfaces. **Default-deny.**

```python
from orqest.mcp import AllowAll, AllowList, DenyAll

DenyAll()                                                    # default
AllowAll()                                                   # DEV ONLY
AllowList([                                                  # production: regex allowlist
    r"^web\.",                                               # web.search, web.fetch
    r"^fs\.",                                                # fs.read, fs.write
    r"^compute_p\d+_latency",
])
```

`PermissionGate` is a Protocol — implement custom (per-user, per-tenant, time-bounded, audit-logged) by writing `async def allow(self, tool_name: str) -> bool`.

**Anchor regex.** `re.search` semantics: `r"web"` matches `cobwebs.compute` too. Use `^...$` or at minimum `^...`.

## Auto-discovery — two integration paths

### Deliberate — `ToolRegistry.get_or_discover`

Called by code that *knows* it needs a tool right now (common at agent-spawn time):

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
# → registered Tool on hit, None on miss
```

Gate consulted before any network call.

### Opportunistic — `DiscoveryHook`

Catches runtime "tool not found" errors from hallucinating LLMs and recovers via discovery:

```python
from orqest.mcp import DiscoveryHook, AllowList
from orqest.hooks import HookRunner

hook = DiscoveryHook(
    registry=registry,
    discovery=MCPDiscovery(),
    manager=manager,
    permission=AllowList([r"^web\.", r"^fs\."]),
    audit_bus=workbench.event_bus,
)
runner = HookRunner(hooks=[hook])
```

Flow when an LLM fabricates `web.scrape_table`:
1. `on_error` detects "tool not found" pattern
2. `MCPDiscovery.search("web.scrape_table")`
3. Gate consulted → `AllowList` matches `^web\.` → permits
4. Connect, adapt, register
5. Returns `Redirect(new_tool="web.scrape_table")` — caller retries with the now-registered tool

Gate denies / discovery fails / not-a-tool-error → `Continue()` (no recovery).

## Audit events

```python
audit_bus = workbench.event_bus      # any EventBus
```

| Event | When |
|---|---|
| `discovery.requested` | A missing tool triggered discovery |
| `discovery.connected` | A discovered tool was registered (one per tool) |
| `discovery.denied` | `PermissionGate` rejected the request |
| `discovery.failed` | Discovery succeeded conceptually but registration failed |

Subscribe handlers that forward to your existing observability layer.

## Orqest as an MCP server

```python
from orqest.autonomy import AgentFactory, MetaOrchestrator, ToolRegistry
from orqest.mcp.server import create_orqest_server

registry = ToolRegistry()
factory = AgentFactory(registry=registry, default_model="openai:gpt-4.1", api_key="sk-...")
meta = MetaOrchestrator(planner=..., factory=factory, registry=registry)

server = create_orqest_server(
    factory=factory, registry=registry, meta=meta,
    default_model="openai:gpt-4.1", api_key="sk-...",
)
# Run: python -m orqest.mcp.server
```

Exposed tools: `create_agent(spec_json)`, `run_agent(name, input)`, `solve_goal(goal)`, `list_agents()`.

Mount in Claude Desktop / Cursor:

```json
{
  "mcpServers": {
    "orqest": { "command": "python", "args": ["-m", "orqest.mcp.server"] }
  }
}
```

Auto-discovery scans `~/.claude.json`, `~/.claude/claude.json`, `~/.config/Claude/claude_desktop_config.json`.

## Pitfalls

- **Don't ship `AllowAll` in production.** It's "remote code execution as a service." Use `AllowList` with anchored regex.
- **Don't expose `create_orqest_server` without transport auth.** With `AllowAll` on the consumer + no auth, you've built a remote shell.
- **Don't trust the tool description from a discovered MCP server.** The description is what the LLM reads to decide whether to call — a malicious server can advertise misleading descriptions. Combine `PermissionGate` with name-allowlisting; add description-validation hooks for high-trust deployments.
- **Don't share `MCPServerManager` across processes.** Each connection holds OS-level handles; cross-process sharing breaks cleanup.
- **Don't lean on `DiscoveryHook` as primary discovery strategy.** Deliberate `get_or_discover` is predictable; the hook is the safety net for hallucinations.
- **Don't auto-register dynamic-discovery into the spawned-agent roster.** A `DynamicAgent` spawned by `MetaOrchestrator` should reference tools from the consumer-wired static registry. Per-agent discovery defeats the audit trail. Discovery is a registry-level decision.

## Where to read more

- `docs/concepts/mcp.md` — full reference (incl. `MCPDiscovery` registry response shape, FastMCP wire format details)
- `references/autonomy.md` — `ToolRegistry` semantics
- `references/healing.md` — `DiscoveryHook` as a tool-level recovery mechanism (counterpart to `FallbackModel` for model-level)
- `docs/concepts/observability.md` — `EventBus` semantics
