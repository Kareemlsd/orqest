# Sandbox

`orqest.sandbox` is the safe-execution surface for LLM-generated Python. The Protocol is small and explicit: **validate then execute.** Three backends ship in core, on a tiered isolation hierarchy; third parties (or future waves) can add `E2BSandbox` / `MicroVMSandbox` / `WasmSandbox` against the same Protocol without touching anything else.

## The four-tier hierarchy

| Tier | Backend | Isolation | When to use |
|---|---|---|---|
| 0 | `InProcessSandbox(unsafe=True)` | none — `exec()` in restricted namespace | tests + tightly-controlled dev workflows |
| 1 | `SubprocessSandbox` (default) | OS process + RLIMIT memory/CPU + outer wall-clock timeout | production single-trusted-tenant; no network/filesystem isolation |
| 2 | `DockerSandbox` | OS process + container (`--cap-drop=ALL --read-only --user 1000:1000 --pids-limit --memory --cpus`); per-session lifecycle; per-user persisted MCP tool library | LLM-authored code from prompt-injection-prone surfaces; production with cross-session tool reuse |
| 3 | `MicroVMSandbox` (deferred) | Firecracker / Kata / gVisor — distinct kernel boundary | adversarial multi-tenant workloads |

**Honest framing.** Tier 2 is hardened *Docker*, not a microVM. Containers share the host kernel. Tier 2 protects against accidental damage and most prompt-injection scenarios; it does *not* protect against adversarial multi-tenant code. For that workload, run inside a microVM (Firecracker / Kata) or use a managed sandbox provider (e2b, Modal). Same language used by Daytona / Modal / Anthropic about their own products.

## Why this exists

The framework already supports runtime *agent* design — `AgentFactory.spawn(AgentSpec)` hydrates an LLM-emitted spec into a live `BaseAgent`. But `AgentSpec.tools` was a wishlist: `AgentFactory._resolve_tools` looked up each `ToolSpec` in `ToolRegistry` and silently dropped the unknowns. So when an LLM requested a brand-new capability, the agent spawned without it.

Closing that loop required two pieces:

1. **A way to carry implementations** in the LLM's emitted spec ([`GeneratedToolSpec`](autonomy.md#dynamic-tool-spawning)).
2. **A safe place to run them** — this module.

Together with [`DynamicToolFactory`](autonomy.md#dynamic-tool-spawning), they let an LLM materialize new tool capabilities at runtime without `eval()` or `exec()` reaching the host process directly.

## The two-stage contract

Every backend implements:

```python
@runtime_checkable
class Sandbox(Protocol):
    async def validate(
        self,
        code: str,
        *,
        allowed_imports: set[str],
    ) -> None: ...

    async def execute(
        self,
        code: str,
        *,
        args: dict[str, Any],
        allowed_imports: set[str],
        timeout_s: float = 5.0,
        memory_mb: int = 128,
    ) -> ExecutionResult: ...
```

* **`validate`** — static AST checks. Raises `ValidationError` on failure. Doesn't execute anything; safe to call from any context including spec-validation pipelines that have no intent to run the code.
* **`execute`** — runs the (pre-validated) implementation with the supplied `args`. **Always returns** `ExecutionResult` — never raises for user-code failures (those land in `result.error`). Reserved for *infrastructure* failures (subprocess crash before handshake completes), which still raise.

`ExecutionResult` carries `success`, `output`, `error`, `stdout`, `duration_ms`. The two-stage split lets consumers reject bad specs at upload time without paying the execution cost.

## Quickstart: running candidate code

The most common use case — "execute this Python function, give me the return value" — is collapsed into a one-line helper. Use this when framework code (not an agent) needs to invoke candidate code directly:

```python
from orqest.sandbox import run_in_sandbox

# Define + call a candidate function in a fresh SubprocessSandbox.
result = await run_in_sandbox(
    "def add(a, b):\n    return a + b",
    return_expression="add(2, 3)",
)
# result == 5
```

What it does: builds a sandbox-friendly implementation (`code + return {expression}`), runs through `SubprocessSandbox` by default, and unwraps the `ExecutionResult` — raising `SandboxRunError(stage, code_snippet, underlying)` on validation or execution failure.

For non-raising semantics (a tuple per call), use `run_in_sandbox_safe`:

```python
from orqest.sandbox import run_in_sandbox_safe

ok, output, error = await run_in_sandbox_safe(
    "while True: pass",
    timeout_s=0.5,
)
# ok == False, error == "sandbox execution failed: sandbox execution timed out after 0.50s"
```

**When to use the helper vs the raw Protocol:**

| Use the helper when… | Use `GeneratedToolSpec` + `DynamicToolFactory` when… |
|---|---|
| Framework code invokes candidate code directly (test harness, evaluator, benchmark) | An *agent* needs to call a tool through pydantic-ai's tool-use loop |
| You want "given code, return value" with one line | You want a `pydantic_ai.Tool` instance the agent's LLM can invoke by name |
| You're iterating over many candidates programmatically | You're hydrating an `AgentSpec` whose `tools` list includes runtime-generated implementations |

Both paths route through the same `Sandbox` Protocol — the same isolation guarantees apply.

## Default-deny imports

`allowed_imports` defaults to **empty**. Validation rejects any `import` or `from … import …` whose top-level module isn't in the set. This closes the most common LLM escape hatch (`import os; os.system(...)`) at the spec layer — before any execution surface is touched.

The full validator (`orqest/sandbox/_static.py`) also rejects:

* **Direct execution / namespace access** — `eval`, `exec`, `compile`, `__import__`, `open`, `globals`, `locals`, `vars`, `input`, `breakpoint`
* **Reflection helpers** — `getattr`, `setattr`, `delattr`, `hasattr`, `type`, `dir`, `super`, `__build_class__`. Blocked because they let user code reach dunders by string lookup (`getattr(obj, "__cla" + "ss__")`), defeating the dunder-attribute blocklist below.
* **Dunder attribute access** — `__class__`, `__bases__`, `__subclasses__`, `__mro__`, `__globals__`, `__builtins__`, `__import__`, `__loader__`, `__spec__`, `__code__`, `__closure__`, `__getattribute__`, `__reduce__`, `__reduce_ex__`, `__dict__`, `__init_subclass__`, `__init__`, `__new__`
* **String-keyed subscript access** to any of the forbidden attributes (`obj["__class__"]`-style reach-through)
* **Bare references** to forbidden names (catches `f = exec` patterns)

The same validator runs in every tier. Tier-1 / Tier-2 subprocess wrappers also restrict `__builtins__` to a curated set (`orqest/sandbox/_safe_builtins.py`) so reflection helpers and the unsafe builtins above aren't even reachable from inside `exec` — defense in depth against any future validator gap.

## Recipe: test-driven loops over LLM-generated code

A common pattern that the Quickstart helper alone doesn't fully explain: you have a *test-driven* loop (an evaluator, a benchmark, a self-improving coder) where every iteration produces a new candidate function from an LLM and you need to run that candidate against several test inputs to see what passed and what failed.

The instinct is to write *one* tool that takes the candidate's source as a string argument and `exec()`s it internally. **This pattern is rejected** by the sandbox validator — `exec`, `eval`, `compile`, `__import__`, `globals`, `locals`, `open`, and the dangerous dunder attributes are all on the forbidden list. The reasoning: a sandbox whose implementation can dynamically execute arbitrary strings against its own namespace has no static safety surface — the whole point of validation is that the *implementation source you sign off at upload time* is the implementation that runs. An exec-based tool defeats that property.

The pattern that *does* work: bake the candidate code into a **fresh `GeneratedToolSpec`** per (iteration × test) and let the sandbox compile + run it once. The implementation is a literal definition + a literal call — no runtime indirection. Each invocation is an independent sandboxed process; the spec carries the full source the validator can inspect.

```python
from orqest.sandbox import SubprocessSandbox, run_in_sandbox

ALLOWED_IMPORTS = {"re", "math", "collections", "itertools", "string"}

async def evaluate_candidate_against_tests(
    candidate_code: str,
    tests: list[tuple[str, object]],  # (call_expression, expected_value)
    sandbox: SubprocessSandbox,
) -> list[bool]:
    """Run a candidate function against each test; return per-test pass/fail."""
    results = []
    for expr, expected in tests:
        # The implementation is the candidate + a direct call. The validator
        # sees concrete Python: `def f(...): ...` followed by `return f(...)`.
        try:
            actual = await run_in_sandbox(
                candidate_code,
                return_expression=expr,  # appended as `return {expr}\n`
                allowed_imports=ALLOWED_IMPORTS,
                sandbox=sandbox,  # reuse for lifecycle efficiency
                timeout_s=4.0,
            )
            results.append(actual == expected)
        except Exception:
            results.append(False)
    return results
```

Why this is safe even when `candidate_code` is LLM-generated:

1. **Static validation runs on the wrapped implementation**, not on `candidate_code` alone. If the candidate imports `os` and `allowed_imports` doesn't include it, validation fails *before* the subprocess launches. No `exec()` ever sees attacker-controlled source unmediated.
2. **The candidate runs inside `SubprocessSandbox`** with `RLIMIT_AS`, `RLIMIT_CPU`, and an outer `asyncio.wait_for` timeout. A runaway loop or memory hog can't damage the parent.
3. **Each invocation is a fresh subprocess**. State doesn't leak between tests; a candidate that crashes test N+1 doesn't pollute test N+2.

What this pattern is *not* designed to defend against:

- **Adversarial multi-tenant code.** Tier 1 shares the host kernel. For that workload, escalate to Tier 2 (`DockerSandbox`) or Tier 3 (microVM).
- **Network egress.** Subprocess sandbox doesn't isolate the network. The candidate can still hit DNS, public APIs, etc. If that matters, run inside a network-isolated namespace (Tier 2 with `--network=none`).
- **Filesystem reads.** Subprocess inherits the parent's working directory. Anything readable by the parent is readable by the candidate.

The Tier-1 sandbox is the right default when the candidate source is *plausibly benign but you want a hard process boundary against bugs and runaway resources*. The full architecture (Tier 0 → 1 → 2 → 3) lets you escalate isolation per workload without rewriting consumer code — the same `Sandbox` Protocol applies to all four.

For the agent-callable counterpart — when an *agent* (not framework code) needs to invoke a tool from inside its LLM tool-use loop — see [`GeneratedToolSpec` + `DynamicToolFactory`](autonomy.md#dynamic-tool-spawning). The two paths share infrastructure; the choice is "who calls the tool, the agent or the framework?"

## `InProcessSandbox` — Tier 0

```python
from orqest.sandbox import InProcessSandbox

sandbox = InProcessSandbox(unsafe=True)   # required kwarg
result = await sandbox.execute(
    "return args['x'] + args['y']",
    args={"x": 3, "y": 4},
    allowed_imports=set(),
)
```

Uses `exec()` in a restricted namespace whose `__builtins__` is a curated whitelist (arithmetic, string, container helpers; *no* `__import__`, `eval`, `exec`, `open`, etc.). User code that writes `import re` is honored via a restricted `__import__` shim that consults `allowed_imports`.

**Constructor refuses without `unsafe=True`.** That's the API — opt-in is mandatory because there is **no real isolation:**

* No event-loop boundary — a `while True` hangs the host
* No memory cap — a `[0] * 10**9` exhausts RAM
* No subprocess spawn cost — but also no subprocess kill possibility
* `__subclasses__` tricks reach `os.system` if the static validator misses a path (we cover the common ones, but the attack surface is wide)

**Use it for tests + tightly-controlled dev workflows.** Never for LLM-generated code from untrusted sources.

## `SubprocessSandbox` — Tier 1, the production default

```python
from orqest.sandbox import SubprocessSandbox

sandbox = SubprocessSandbox()
result = await sandbox.execute(
    "import re\nreturn re.findall(r'\\d+', args['text'])",
    args={"text": "a1 b22 c333"},
    allowed_imports={"re"},
    timeout_s=2.0,
    memory_mb=64,
)
```

Each `execute` boots a fresh `python -c <wrapper>` subprocess that:

1. Reads JSON args from stdin
2. **Re-validates** the implementation against `allowed_imports` (defense in depth — the parent already validated, but a misconfigured parent shouldn't be the only line of defense)
3. Imports only the allowed modules
4. Defines a function whose body is the implementation
5. Calls it with `**args`
6. JSON-encodes the result to stdout

Resource enforcement (POSIX):

* `RLIMIT_AS` from `memory_mb` (address-space cap; rejects the `[0] * 10**9` allocation pattern)
* `RLIMIT_CPU` from `timeout_s + 1` (CPU-time cap; backstop for the outer wall-clock timeout)
* Outer `asyncio.wait_for(timeout_s)` (kills the subprocess on timeout)

**Windows:** `resource.setrlimit` is unavailable. The class still constructs and works, but logs a one-time WARNING that memory/CPU caps are not enforced — only the outer wall-clock timeout applies. Use a containerized backend (W3.L / W3.M) for hard isolation on Windows.

**What it does NOT protect against:**

* **Network access** — the subprocess can still hit the network. For network isolation, use a third-party Docker / Firecracker / e2b backend.
* **Filesystem reads** — the subprocess inherits the parent's working directory and can read any file the parent can.
* **Child subprocess spawning** if the CPU cap is high enough.

Per-invocation overhead is roughly 50–100ms (subprocess startup). For hot paths, plan for a future `SubprocessPoolSandbox` (W3.K) that amortizes startup across calls.

## `DockerSandbox` — Tier 2

```python
from uuid import uuid4
from orqest import Workbench
from orqest.memory import LocalMemoryStore

wb = Workbench(
    user_id="alice",                       # required — framework-issued, never LLM-visible
    session_id=str(uuid4()),               # required — same
    memory=LocalMemoryStore(":memory:"),
)

async with wb.with_docker_sandbox(
    image="orqest/agent-runtime:0.8.0",
    allowed_packages={"pandas", "re", "json"},
    promotion_policy="threshold",           # | "eager" | "operator_approval"
    promotion_threshold=3,
) as sandbox:
    result = await sandbox.execute(
        "import re\nreturn re.findall(r'\\d+', args['t'])",
        args={"t": "a1 b22 c333"},
        allowed_imports={"re"},
        agent_id="alice",                  # per-agent venv inside the container
        timeout_s=2.0,
    )
# Container removed on exit; the per-user volume `orqest-user-alice` persists
```

Each `with_docker_sandbox(...)` opens a fresh container from the published `orqest/agent-runtime:<version>` image. Lifecycle:

1. **`__aenter__`** — `docker run` with the hardened flag set (cap-drop=ALL, read-only root, tmpfs `/workspace`, `--user 1000:1000`, memory + CPU + pids limits, port-publish `127.0.0.1:0:8000`, named volume `orqest-user-<user_id>:/data`). Mints a per-construction HMAC secret + JWT bearer; waits up to 30s for the in-container FastMCP server's `/mcp` endpoint to accept `initialize`. Opens an MCP client over Streamable HTTP, attaching `Authorization: Bearer <JWT>`.
2. **`execute(code, ..., agent_id=..., dependencies=[...])`** — calls the container's `execute_python` MCP tool. Inside the container: per-agent `uv venv` is created if absent (~50 ms); declared `dependencies` are installed by `uv pip install` IFF they're in the operator-supplied `allowed_packages` allowlist (else fail-closed); the same AST validator runs again as defense-in-depth; subprocess into the agent's venv with `RLIMIT_AS` + `RLIMIT_CPU`.
3. **`__aexit__`** — closes the MCP connection, `docker rm -f`s the container. The named volume **persists** — that's the per-user tool library (next bullet).

**Per-user persisted tool library.** The volume `orqest-user-<user_id>:/data` holds an SQLite database (`/data/orqest-tools.sqlite`). When successful invocations of the same tool name + code-hash hit the threshold, the in-container server *self-promotes* the tool: persists it to SQLite + registers it as a first-class MCP tool + fires `notifications/tools/list_changed`. Alice's NEXT session for the same `user_id` opens a fresh container that mounts the same volume; on startup, the server replays the SQLite library into the registry; her promoted tools appear in the first `tools/list` response — no respawn needed. Cross-user isolation is enforced by the named volume scope (`orqest-user-bob` is a different volume).

**Three promotion policies.** `"threshold"` (default, N=3 successful invocations of the same `(name, code_hash)`); `"eager"` (every successful invocation); `"operator_approval"` (the framework emits `tool.promotion_pending` on the bus; consumer code or a human approves via `promote_tool`).

**JWT scope separation.** `promote_tool` and `forget_tool` reject agent-scope tokens — they require an `operator`-scope JWT. The host-side `DockerSandbox._mint_jwt` stamps `scope: "agent"` into every bearer the LLM-facing MCP connection uses, so the LLM cannot reach these tools through its normal path even when the underlying transport is shared. Host orchestrators that genuinely want to promote (or forget) call `DockerSandbox.mint_operator_token()` and use that bearer directly. Tokens without an explicit `scope` claim default to `agent` — least privilege.

**Origin enforcement.** `ORQEST_ALLOWED_ORIGINS` defaults to `http://127.0.0.1,http://localhost` when unset — DNS-rebinding defense per the MCP spec is on by default. Operators with custom hostnames override via the env var; setting it to `""` is the documented escape hatch for "no check at all".

**Identifier hardening.** `user_id` and `session_id` (validated at `DockerSandbox.__init__`) and `agent_id` (validated at the in-container `execute_python` MCP boundary) must match `^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$`. Path-traversal attempts like `agent_id="../escape"` are rejected with a clear `ValueError` before any filesystem operation runs.

**Honest threat model.** Containers share the host kernel. The Docker tier hardens against accidental damage (LLM writing `rm -rf /` won't survive `--read-only`) and most prompt-injection scenarios (`--cap-drop=ALL` removes the capabilities most exploits depend on; per-user volume isolation prevents cross-user data leakage; JWT auth on every MCP call prevents siblings from running each other's code). It does *not* protect against adversarial code that targets the kernel directly — three runc CVEs in November 2025 alone allowed container-escape from inside. For adversarial multi-tenant workloads, run inside a microVM (Firecracker/Kata) or use a managed sandbox provider — that's Tier 3.

**Networking.** v0.8.0 uses `--network=bridge` because port-publish requires it. LLM-authored code that would reach the network needs the relevant module in `allowed_imports` (default empty) AND the relevant package in `allowed_packages` (default empty). Custom egress allowlist (custom bridge + iptables) is a future operator-driven seam.

**Setup.** Build the image once: `docker buildx build --build-arg ORQEST_VERSION=0.8.0 -t orqest/agent-runtime:0.8.0 .` (Dockerfile at repo root). Install the host-side dep group: `uv sync --group docker` (pulls `docker>=7.0` + `httpx>=0.27`).

## `DynamicToolFactory` integration

The matching consumer is `orqest.autonomy.DynamicToolFactory`:

```python
from orqest.autonomy import DynamicToolFactory, GeneratedToolSpec
from orqest.sandbox import SubprocessSandbox

factory = DynamicToolFactory(SubprocessSandbox())
tool = await factory.spawn(GeneratedToolSpec(
    name="extract_dois",
    description="Extract DOIs from a text blob.",
    parameters={"text": {"type": "string"}},
    implementation=(
        "import re\n"
        "return {'dois': re.findall(r'10\\.\\d{4,}/[\\w.\\-/]+', args['text'])}\n"
    ),
    allowed_imports={"re"},
    timeout_s=2.0,
))
# tool is a real pydantic_ai.Tool — bind it to a BaseAgent or pass it
# inside an AgentSpec for runtime spawning. See concepts/autonomy.md.
```

See [Dynamic tool spawning](autonomy.md#dynamic-tool-spawning) in the autonomy concept doc for the `AgentSpec` integration story (mixed registered + generated tools, `BaseAgent.add_tool` for runtime assignment to existing agents, etc.).

## Bus events

When a `bus` is supplied to `DynamicToolFactory`, the following events fire on the standard `EventBus`:

| Event | When | Payload |
|---|---|---|
| `tool.spawned` | Successful spawn | `{tool_name}` |
| `tool.spawn_failed` | `validate` rejected the spec | `{tool_name, reason}` |
| `sandbox.validation_rejected` | Same — sandbox-layer namespace | `{tool_name, reason}` |
| `tool.invocation_completed` | Successful `execute` | `{tool_name, duration_ms}` |
| `tool.invocation_failed` | Failed `execute` | `{tool_name, error, duration_ms}` |

Subscribe to these for an audit log of LLM-generated tool activity.

## Future seams (deferred)

- **W3.J — Procedural-memory persistence (shipped via per-user library).** Phase 13 ships per-user container-side tool persistence; the host-side `LocalMemoryStore` mirror with `memory_type="tool"` is the in-progress complement for orqest-side discoverability + observability.
- **W3.K — `SubprocessPoolSandbox`.** Reuse pre-warmed subprocesses to amortize Tier-1 startup cost.
- **W3.L — `E2BSandbox`.** Hosted microVM backend via `e2b`. Optional dependency.
- **W3.M — `DockerSandbox` (shipped 2026-05-16).** Per-session container; per-user persisted MCP tool library; HMAC-JWT auth.
- **Tier 3 — `MicroVMSandbox`.** Firecracker/Kata/gVisor — distinct kernel boundary; the right tier for adversarial multi-tenant code.
- **W3.C — ADAS sandboxed codegen.** With the sandbox in core, `MetaAgentSearch` can let the meta agent emit raw Python `forward()` for cases compositions of registered primitives can't express.

## Runnable demo

[`notebooks/11_dynamic_tools.ipynb`](https://github.com/Kareemlsd/orqest/blob/main/notebooks/11_dynamic_tools.ipynb) — three sandbox tiers (`InProcessSandbox`, `SubprocessSandbox`, `DockerSandbox`) executing `GeneratedToolSpec`s end-to-end, with the LLM using a tool it didn't have at construction.
