# Sandbox — reference

Compressed judgment layer over `orqest/sandbox/`. For full reference, read `docs/concepts/sandbox.md`.

## The four-tier hierarchy

| Tier | Backend | Isolation | When to use |
|---|---|---|---|
| 0 | `InProcessSandbox(unsafe=True)` | none — `exec()` in restricted namespace | tests + tightly-controlled dev workflows |
| 1 | `SubprocessSandbox` (default) | OS process + RLIMIT memory/CPU + outer wall-clock timeout | production single-trusted-tenant; no network/filesystem isolation |
| 2 | `DockerSandbox` | OS process + container (cap-drop=ALL, read-only, --user 1000:1000, mem+cpu+pids limits); per-session lifecycle; per-user persisted MCP tool library | LLM-authored code from prompt-injection-prone surfaces |
| 3 | `MicroVMSandbox` (deferred) | Firecracker / Kata / gVisor — distinct kernel boundary | adversarial multi-tenant workloads |

**Honest framing.** Tier 2 is hardened Docker, not a microVM. Containers share the host kernel. Tier 2 protects against accidental damage and most prompt-injection scenarios; it does *not* protect against adversarial multi-tenant code. For that, escalate to Tier 3.

## The two-stage Protocol

```python
from orqest.sandbox import Sandbox, ExecutionResult, ValidationError

class Sandbox(Protocol):
    async def validate(self, code: str, *, allowed_imports: set[str]) -> None: ...
    async def execute(
        self, code: str, *, args: dict, allowed_imports: set[str],
        timeout_s: float = 5.0, memory_mb: int = 128,
    ) -> ExecutionResult: ...
```

- **`validate`** — static AST checks. Raises `ValidationError` on failure. Doesn't execute anything; safe in spec-validation pipelines with no execute intent.
- **`execute`** — runs the (pre-validated) implementation. **Always returns** `ExecutionResult` for user-code failures (lands in `result.error`). Reserved exceptions are infrastructure failures (subprocess crash before handshake).

`ExecutionResult` carries `success`, `output`, `error`, `stdout`, `duration_ms`. The two-stage split lets consumers reject bad specs at upload time without paying the execution cost.

## Quickstart — `run_in_sandbox` / `run_in_sandbox_safe`

When framework code (not an agent) needs to invoke candidate code directly:

```python
from orqest.sandbox import run_in_sandbox, run_in_sandbox_safe, SandboxRunError

# Raises on failure (validation OR execution)
result = await run_in_sandbox(
    "def add(a, b):\n    return a + b",
    return_expression="add(2, 3)",
)                                                            # → 5

# Tuple return; never raises
ok, output, error = await run_in_sandbox_safe(
    "while True: pass",
    timeout_s=0.5,
)                                                            # → (False, None, "sandbox execution failed: ...")
```

When to use the helper vs `GeneratedToolSpec` + `DynamicToolFactory`:

| Helper (`run_in_sandbox`) | `GeneratedToolSpec` + `DynamicToolFactory` |
|---|---|
| Framework code invokes candidate code directly (test harness, evaluator, benchmark) | An *agent* needs to call a tool through pydantic-ai's tool-use loop |
| "Given code, return value" with one line | Want a `pydantic_ai.Tool` instance the agent's LLM invokes by name |
| Iterating programmatically over many candidates | Hydrating an `AgentSpec` whose `tools` list includes runtime-generated implementations |

Both route through the same `Sandbox` Protocol — same isolation guarantees.

## Default-deny imports

`allowed_imports` defaults to **empty**. The AST validator rejects:

- Any `import` / `from … import …` whose top-level module isn't in `allowed_imports`
- Forbidden builtins: `eval`, `exec`, `compile`, `__import__`, `open`, `globals`, `locals`, `vars`, `input`, `breakpoint`
- Dunder attributes: `__class__`, `__bases__`, `__subclasses__`, `__mro__`, `__globals__`, `__builtins__`, `__loader__`, `__spec__`, `__code__`, `__closure__`, `__getattribute__`, `__reduce__`, `__reduce_ex__`
- Bare references to forbidden names (catches `f = exec` patterns)

The same validator is used by both `InProcessSandbox` and `SubprocessSandbox` for behavioral consistency.

## Tier 0 — `InProcessSandbox`

```python
from orqest.sandbox import InProcessSandbox

sandbox = InProcessSandbox(unsafe=True)                      # required kwarg
result = await sandbox.execute(
    "return args['x'] + args['y']",
    args={"x": 3, "y": 4},
    allowed_imports=set(),
)
```

**Constructor refuses without `unsafe=True`.** Opt-in is mandatory — there is **no real isolation:**
- No event-loop boundary — `while True` hangs the host
- No memory cap — `[0] * 10**9` exhausts RAM
- `__subclasses__` tricks reach `os.system` if the validator misses a path

Use it for tests + tightly-controlled dev workflows. Never for LLM-generated code from untrusted sources.

## Tier 1 — `SubprocessSandbox` (production default)

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

Each `execute` boots a fresh `python -c <wrapper>` subprocess that re-validates (defense in depth), imports only the allowed modules, defines a function with the implementation, and JSON-encodes the result. Resource caps (POSIX): `RLIMIT_AS` from `memory_mb`, `RLIMIT_CPU` from `timeout_s + 1`, outer `asyncio.wait_for(timeout_s)`.

**Windows:** `resource.setrlimit` is unavailable. Class still works, logs a one-time WARNING that memory/CPU caps are unenforced (only outer timeout applies). Use Tier 2 for hard isolation on Windows.

**What it does NOT protect against:** network access (subprocess can hit DNS, public APIs); filesystem reads (inherits parent's cwd); child subprocess spawning if the CPU cap is high enough.

Per-invocation overhead: 50-100ms (subprocess startup). Future seam: `SubprocessPoolSandbox` (W3.K) for pool-amortized startup.

## Tier 2 — `DockerSandbox`

```python
from uuid import uuid4
from orqest import Workbench
from orqest.memory import LocalMemoryStore

wb = Workbench(
    user_id="alice",                                          # required — framework-issued, never LLM-visible
    session_id=str(uuid4()),                                  # required
    memory=LocalMemoryStore(":memory:"),
)

async with wb.with_docker_sandbox(
    image="orqest/agent-runtime:0.8.0",
    allowed_packages={"pandas", "re", "json"},
    promotion_policy="threshold",                             # | "eager" | "operator_approval"
    promotion_threshold=3,
) as sandbox:
    result = await sandbox.execute(
        "import re\nreturn re.findall(r'\\d+', args['t'])",
        args={"t": "a1 b22 c333"},
        allowed_imports={"re"},
        agent_id="alice",                                     # per-agent venv inside the container
        timeout_s=2.0,
    )
# Container removed on exit; volume `orqest-user-alice` persists
```

Each `with_docker_sandbox` opens a fresh container from the published `orqest/agent-runtime:<version>` image. Hardened: cap-drop=ALL, read-only root, tmpfs /workspace, --user 1000:1000, memory + CPU + pids limits, port-publish 127.0.0.1:0:8000, named volume `orqest-user-<user_id>:/data`. Per-construction HMAC secret + JWT bearer auth.

**Per-user persisted tool library.** The volume holds a SQLite DB. When `(name, code_hash)` invocations hit `promotion_threshold` successes, the in-container server self-promotes the tool: persists to SQLite, registers as first-class MCP tool, fires `notifications/tools/list_changed`. Alice's NEXT session for the same `user_id` mounts the same volume; tools appear in the first `tools/list` response — no respawn needed. Cross-user isolation is enforced by volume scope (`orqest-user-bob` is separate).

**Three promotion policies.** `"threshold"` (default, N successful invocations); `"eager"` (every success); `"operator_approval"` (emits `tool.promotion_pending` on the bus; consumer/human approves via `promote_tool`).

**JWT scope separation.** `promote_tool` and `forget_tool` require an `operator`-scope JWT. The agent-facing MCP connection holds an `agent`-scope token (what `DockerSandbox._mint_jwt` stamps by default), so the LLM cannot bypass the promotion gate. Host code that needs to promote calls `DockerSandbox.mint_operator_token()` and uses that bearer directly.

**Origin allowlist** defaults to `http://127.0.0.1,http://localhost` when unset (DNS-rebinding defense). Override via `ORQEST_ALLOWED_ORIGINS`; set to `""` to disable.

**Identifier validation.** `user_id` / `session_id` / `agent_id` must match `^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$` (alphanumeric start; alphanum/_/-; max 64 chars). Rejected at `DockerSandbox.__init__` and at the in-container `execute_python` boundary — closes `agent_id="../escape"` path-traversal.

**Setup.** Build the image once: `docker buildx build --build-arg ORQEST_VERSION=0.8.0 -t orqest/agent-runtime:0.8.0 .`. Host deps: `uv sync --group docker`.

## `DynamicToolFactory` — the agent-callable path

```python
from orqest.autonomy import DynamicToolFactory, GeneratedToolSpec
from orqest.sandbox import SubprocessSandbox

factory = DynamicToolFactory(SubprocessSandbox())
tool = await factory.spawn(GeneratedToolSpec(
    name="extract_dois",
    description="Extract DOIs from a text blob.",
    parameters={"text": {"type": "string"}},
    implementation="import re\nreturn {'dois': re.findall(r'10\\.\\d{4,}/[\\w.\\-/]+', args['text'])}\n",
    allowed_imports={"re"},
    timeout_s=2.0,
))
# tool is a real pydantic_ai.Tool — bind it to a BaseAgent or pass it
# inside an AgentSpec for runtime spawning. See references/autonomy.md.
```

## Bus events (from `DynamicToolFactory`)

| Event | When |
|---|---|
| `tool.spawned` | Successful spawn |
| `tool.spawn_failed` | `validate` rejected the spec |
| `sandbox.validation_rejected` | Same — sandbox-layer namespace |
| `tool.invocation_completed` | Successful `execute` |
| `tool.invocation_failed` | Failed `execute` |

## Pitfalls

- **`InProcessSandbox` is a footgun without `unsafe=True`.** The kwarg is the contract. Don't bypass.
- **Default `allowed_imports=set()`.** Explicit allowlist required for any non-trivial code. Don't propagate the default into production.
- **Don't write tools that `exec()` user-supplied code at runtime.** The sandbox validator rejects `exec`/`eval`/`compile`/`__import__` — the whole point of static validation is that the implementation source you sign off at upload time is the implementation that runs. For test-driven loops over LLM candidates, bake the candidate into a **fresh `GeneratedToolSpec`** per iteration; each invocation is its own validator-checked subprocess.
- **Tier 1 doesn't isolate network or filesystem.** For network/FS isolation, use Tier 2 with `--network=none` (custom egress allowlist is a future seam).
- **Tier 2's threat model excludes adversarial multi-tenant code.** Containers share the host kernel. For that workload, escalate to Tier 3 (microVM) or a managed sandbox provider.
- **`agent_id` on `DockerSandbox.execute` scopes the per-agent venv.** Don't conflate with `user_id` (the cross-session library isolation key).

## Where to read more

- `docs/concepts/sandbox.md` — full reference (incl. test-driven-loop recipe, threat model, future seams)
- `references/autonomy.md` — `GeneratedToolSpec` + `DynamicToolFactory` + `AgentFactory(tool_factory=...)` integration
- `notebooks/11_dynamic_tools.ipynb` — all three tiers executing `GeneratedToolSpec`s end-to-end
