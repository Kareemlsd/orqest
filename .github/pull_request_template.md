<!--
Thanks for contributing to Orqest! Please fill out the sections below.
See CONTRIBUTING.md for the full process.
-->

## Summary

<!-- What does this PR change and why? Link any related issue: "Closes #123". -->

## Type of change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that changes existing behavior)
- [ ] Docs / chore (no runtime behavior change)

## Checklist

- [ ] I branched off `main` and kept the diff focused on one logical change.
- [ ] `uv run ruff check orqest/` passes.
- [ ] `uv run ruff format --check orqest/` passes.
- [ ] `uv run pytest tests/ -m "not docker" -q` passes.
- [ ] `uv run mkdocs build --strict` passes (if docs/behavior changed).
- [ ] I added or updated tests for the change.
- [ ] I updated docs/`CHANGELOG.md` where relevant.
- [ ] No secrets, API keys, or credentials are included in this PR.

## Security impact

<!--
Does this touch the sandbox (orqest/sandbox/), the in-container runtime,
authentication, CI/CD, or publishing? If so, describe the impact. If not, write
"None". See SECURITY.md.
-->
