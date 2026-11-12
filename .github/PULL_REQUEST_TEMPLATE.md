<!--
Thanks for contributing to erdify! Fill in every section; the "PR description"
check fails while Summary, Related issues or How it was tested is empty.
Release PRs ("chore: release X.Y.Z") use .github/release-pr-template.md instead.
-->

## Summary

<!-- What does this PR change, and why? For a bug fix: what was drawn wrong, and what is drawn now. -->

## Related issues

<!-- "Closes #123" for every issue this PR resolves; "Follow-up: #456" for issues filed for what is left. Write "None" if there is no issue. -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Documentation
- [ ] Refactor / maintenance
- [ ] CI / tooling

## Output impact

<!-- See docs/stability.md. Pick one and explain if it is not "none". -->

- [ ] None: the generated diagrams (PlantUML / Mermaid / JSON / HTML) don't change
- [ ] Output changes: existing diagrams change, so `erdify --check` fails once after upgrading (CHANGELOG `### Output changes`)
- [ ] Breaking: a CLI flag, config key, exit code or public API changes (CHANGELOG `### Changed — **breaking**`)

## How it was tested

<!--
Which tests were added or changed, and what they cover. For parser changes:
- a regression test with a minimal model snippet,
- for SQLAlchemy / SQLModel / Django: a module in the edge-case catalog
  (tests/fixtures/*_edge_cases/) and a passing ground-truth comparison
  (tests/test_ground_truth_*.py), or the KNOWN_DIFFERENCES / LIMITATIONS entry
  you added and why.
-->

## Checklist

- [ ] `uv run pytest` passes locally
- [ ] `uv run ruff check src/ tests/` and `uv run mypy src/` pass
- [ ] `CHANGELOG.md` has an entry under `[Unreleased]` (or the change is not user-visible)
- [ ] Docs match the change: `docs/features.md`, `docs/frameworks/limitations.md`, the framework pages, README, `docs/usage/cli.md` (regenerate with `scripts/gen_cli_docs.py`)
- [ ] Golden files / `docs/examples` regenerated if the output changed
- [ ] Supported-version changes update `docs/installation.md`, the CI matrix and the CHANGELOG together
- [ ] Everything is in English (code, comments, docs, commit messages)
