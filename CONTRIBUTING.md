# Contributing to Orqest

Thanks for your interest in contributing! Orqest is a Python framework for
building autonomous agentic AI systems on top of
[pydantic-ai](https://github.com/pydantic/pydantic-ai). This guide explains how
to get set up, the standards we hold code to, and how changes get merged.

By participating you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## TL;DR

```bash
# 1. Fork + clone, then create a branch off main
git checkout -b feat/my-change origin/main

# 2. Install (editable, with dev + docs + optimization groups)
uv sync --group dev --group docs --group optimization

# 3. Make your change, then run the gate locally before pushing
uv run ruff check orqest/
uv run ruff format --check orqest/
uv run pytest tests/ -m "not docker" -q
uv run mkdocs build --strict

# 4. Push and open a PR against main
```

All four checks above are what CI enforces. If they pass locally, the PR's
required checks should pass too.

## Development setup

We use [`uv`](https://docs.astral.sh/uv/) for environment and dependency
management. Python **3.12+** is required (CI runs 3.12 and 3.13).

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync all dependency groups used by CI
uv sync --group dev --group docs --group optimization
```

Optional groups:

- `--group docker` — only needed to run the 13 Docker-sandbox tests (they are
  marked `docker` and skipped by default; they also require a running Docker
  daemon and the `orqest/agent-runtime` image).

## Running the checks

| Check | Command | What it enforces |
|-------|---------|------------------|
| Lint | `uv run ruff check orqest/` | Style + common bug patterns |
| Format | `uv run ruff format --check orqest/` | Consistent formatting |
| Tests | `uv run pytest tests/ -m "not docker" -q` | The full default suite |
| Docs | `uv run mkdocs build --strict` | Docs build with no warnings |

Run a single test file or test by name:

```bash
uv run pytest tests/agents/test_base_agent.py -v
uv run pytest tests/ -k "test_refinement_loop_converges" -v
```

**Never require real API keys for the default suite.** Mock the model layer.
The CI-blocking suite must run offline.

## Coding standards

Orqest follows
[Pragmatic Programmer](https://pragprog.com/titles/tpp20/the-pragmatic-programmer-20th-anniversary-edition/)
principles — orthogonality, DRY, YAGNI, ETC (Easy to Change). Concretely:

- **Async-first.** Every agent-touching path is `async def`.
- **Pydantic everywhere.** State, output, memory entries, plan tasks are Pydantic
  `BaseModel`. Config uses frozen dataclasses.
- **Generic typing.** Always specify type parameters
  (`BaseAgent[StateT, OutputT]`, `Pipeline[InputT, OutputT]`, …).
- **Explicit dependencies.** No import-time side effects; functions take deps as
  arguments.
- **Build on pydantic-ai.** We wrap, compose, and bridge — we do not
  re-implement. Models, Tools, and `ModelMessage`s are pydantic-ai native types.
- **Match the surrounding code.** Comment density, naming, and idioms should look
  like the file you're editing.

The `docs/concepts/` reference and the `notebooks/` tour are the entry surface —
new behavior usually needs a doc and, for a new battery, a benchmark (see
[`benchmarks/README.md`](benchmarks/README.md)).

### Tests are required

Bug fixes and features need tests. Tests mirror the source layout under
`tests/`. We use `pytest` + `pytest-asyncio`. Property-based tests
(Hypothesis) are welcome where they fit.

## Pull request process

1. **Branch off `main`.** One logical change per PR. Keep diffs focused.
2. **Run the gate locally** (lint, format, tests, docs) before pushing.
3. **Open the PR against `main`** and fill out the PR template.
4. **CI must pass.** The `pytest + ruff + mkdocs (py3.12)` and `(py3.13)` checks
   are required and block merge.
5. **One approving review is required** before merge. Code owners
   (see [`.github/CODEOWNERS`](.github/CODEOWNERS)) are requested automatically
   for sensitive paths (workflows, the sandbox, packaging).
6. **Keep your branch current** with `main` and resolve all review threads.
7. Squash or rebase merges are both fine; the branch is deleted on merge.

Direct pushes to `main` are blocked — everything goes through a PR.

## Security-sensitive areas

Orqest executes **LLM-generated Python** inside its sandbox tiers
(`orqest/sandbox/`). Changes there, to the in-container runtime
(`orqest/sandbox/docker_runtime/`), to authentication (`orqest/sandbox/jwt.py`,
`auth.py`), or to CI/publishing workflows receive extra scrutiny and require
code-owner review. If you believe you've found a vulnerability, **do not open a
public issue** — follow [`SECURITY.md`](SECURITY.md).

## Reporting bugs / requesting features

Use the issue templates. Good bug reports include a minimal reproduction, the
expected vs. actual behavior, and your Python/OS versions.

## License

By contributing, you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
