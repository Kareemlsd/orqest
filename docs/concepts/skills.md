# Skills

Orqest ships an **agentic-IDE skill** as package data. A skill is a
self-contained orientation document that an LLM coding assistant
(Claude Code, Cursor, Aider, or any other tool that reads the
`.claude/skills/` convention) can load when it needs to write code
against Orqest. The skill teaches the assistant how to use the library
without occupying space in your project's source tree.

The skill is bundled with every PyPI release and installed into a
target project's skills directory by a single command.

## Install the bundled skill

```bash
python -m orqest.skills install
```

The default target is `./.claude/skills/`. The command copies the
bundled `orqest/` skill folder into that directory.

To install at a different location:

```bash
python -m orqest.skills install ~/.claude/skills   # global install
python -m orqest.skills install path/to/skills/    # custom path
```

Re-running the command on a project that already has the skill exits
non-zero with a message asking for `--force`:

```bash
python -m orqest.skills install --force
```

The install command is idempotent: with `--force`, the existing
`orqest/` subdirectory is removed and replaced.

## What the skill contains

The skill folder has the following layout:

```
orqest/
├── SKILL.md
└── references/
    ├── orchestration.md
    ├── memory.md
    ├── autonomy.md
    ├── healing.md
    ├── metacognition.md
    ├── mcp.md
    ├── optimization.md
    ├── generative-ui.md
    └── sandbox.md
```

`SKILL.md` is the orientation document. It contains:

- A decision tree mapping common tasks to the right primitive.
- Five paste-ready wire-up patterns covering ~80% of real usage.
- A pitfalls section listing the mistakes that bite most often.
- The public API surface of the root namespace.

The nine files under `references/` are compressed judgment-layer
references for each battery. The assistant loads only the references
relevant to the task at hand, keeping the context footprint small.

Each reference file points back at the corresponding concept page in
this documentation site for full depth. The references are deliberately
terse; the concept docs are the single source of truth for the API
surface.

## How the assistant uses it

An agentic IDE that follows the `.claude/skills/` convention looks for
SKILL.md files in the project's skills directory and loads the
matching skill when its activation criteria are met. For Orqest, the
activation criteria are described in the `description` field of the
skill's frontmatter: any project that imports from `orqest`, that
mentions Orqest primitives by name, or that composes agents with
Orqest's orchestration shapes triggers the skill.

When triggered, the assistant loads `SKILL.md` first, then opens the
specific reference files it needs to answer the current task.

## Drift protection

The skill's references contain working Python snippets that import
symbols from the `orqest` package. If a future release renames a
symbol or moves it between modules, those snippets would silently
break.

`tests/skills/test_skill_drift.py` runs on every CI build and resolves
every `from orqest...` import that appears in the skill files against
the actual package. The test fails if any import becomes unresolvable.
The guarantee is: every public symbol referenced from the bundled
skill resolves against the installed package.

## When to install globally vs per project

Two options:

- **Per project (default).** The skill lives in
  `<project>/.claude/skills/orqest/` and ships with the project's
  repository. Each project can pin the skill to the version of Orqest
  it depends on.
- **Global.** The skill lives in `~/.claude/skills/orqest/` and is
  shared across every project on the machine. Simpler to maintain but
  loses per-project version pinning.

For libraries that develop against multiple Orqest versions, per-
project is the safer choice.

## See also

- [`orqest.skills`](https://github.com/Kareemlsd/orqest/tree/main/orqest/skills/orqest)
  — the bundled skill source on GitHub.
- The decision tree and wire-up patterns inside `SKILL.md` are the
  fastest way to orient a new assistant on Orqest.
