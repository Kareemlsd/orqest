# Security Policy

## Supported versions

Orqest is pre-1.0 (currently `0.8.0`). Security fixes are applied to the latest
release on `main`. There is no long-term support branch yet.

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues,
discussions, or pull requests.**

Instead, use one of the following private channels:

1. **GitHub Security Advisories** (preferred) — open a private report via the
   repository's **Security → Report a vulnerability** tab
   ([Privately reporting a security vulnerability](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)).
2. **Email** — `k.elsayed@outlook.com` with the subject line
   `[orqest security]`.

Please include:

- A description of the vulnerability and its impact.
- Steps to reproduce (a minimal proof of concept is ideal).
- Affected version/commit.
- Any suggested remediation.

We aim to acknowledge reports within **5 business days** and to provide a
remediation timeline after triage. Please give us a reasonable window to release
a fix before any public disclosure (coordinated disclosure).

## Threat model — what Orqest treats as untrusted

Orqest is a framework for autonomous agents, and several subsystems are designed
to handle **untrusted, LLM-generated input**. Contributors and consumers should
understand these boundaries:

- **The sandbox tiers (`orqest/sandbox/`) execute LLM-authored Python.** Safety
  rests on layered defenses: a static AST validator (`_static.py`,
  default-deny imports + forbidden-name/reflection checks), a restricted
  `__builtins__` (`_safe_builtins.py`), subprocess resource limits
  (`RLIMIT_AS` / `RLIMIT_CPU`), and — at Tier 2 — per-session Docker isolation.
  - `InProcessSandbox` (Tier 0) is **opt-in via `unsafe=True`** and offers no
    isolation; it must never run untrusted code.
  - `SubprocessSandbox` (Tier 1) and `DockerSandbox` (Tier 2) are the supported
    surfaces for code you do not control.
- **The in-container runtime (`orqest/sandbox/docker_runtime/`)** runs an
  HMAC-JWT-authenticated FastMCP server with scope separation (`agent` vs.
  `operator`). Identifier inputs (`user_id` / `session_id` / `agent_id`) are
  validated against a strict grammar to prevent path traversal.
- **Tool/agent specs, memory contents, and topology specs** may originate from a
  model and should be treated as untrusted data, not code.

When changing any of these areas, assume the input is adversarial. Defense
regressions are treated as security bugs even if no exploit is demonstrated.

## What is in scope

- Sandbox escapes or bypasses of the static validator / restricted builtins.
- Authentication/authorization flaws in the Docker runtime (JWT, scope checks,
  Origin allowlist).
- Path traversal, SSRF, or injection via identifiers, MCP discovery, or web
  tools.
- Supply-chain issues in CI/CD or the publish pipeline.

## What is out of scope

- Vulnerabilities in third-party dependencies that are already publicly tracked
  (report those upstream; we consume Dependabot alerts for them).
- Misconfiguration by a consuming application that disables Orqest's defaults
  (e.g. running `InProcessSandbox(unsafe=True)` on untrusted code, or widening
  `ORQEST_ALLOWED_ORIGINS`).
- Denial of service from resource limits that the consumer chose to raise.
