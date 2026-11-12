<!--
Release PR template. Open with:
  gh pr create --title "chore: release X.Y.Z" --label release --body-file .github/release-pr-template.md
then fill it in (gh pr edit --body-file ...).
Title: "chore: release X.Y.Z". Keep the PR pure: version, CHANGELOG, uv.lock and
the `rev:` references only. Land anything else in its own PR first.
-->

## Release

- **Version:** X.Y.Z (previous: X.Y.Z)
- **Type:** patch / minor / major
- **Why this type:** <!-- Per docs/stability.md: patch = fixes and output changes only; minor = new features, flags, frameworks or supported versions; major = anything under "Changed — **breaking**". -->

## What ships

<!-- One line per merged PR since the last release, with the issues it closes. -->

- #PR — short description (closes #…)

## Highlights

<!-- 2–5 bullets in user terms: what users get, which setups are affected. These seed the release notes and the announcement. -->

## Upgrade impact

<!-- Copy the CHANGELOG's "Output changes" and "Changed — **breaking**" text in short, or write "None". Name the frameworks / setups whose diagrams change, so users know whether `erdify --check` fails once. -->

## Supported versions

<!-- Changes to supported Python / SQLModel / SQLAlchemy / Django / Pydantic / sqlglot versions, or "No changes". -->

## Release checklist

<!-- Every box must be ticked; tick an item that doesn't apply and say so ("n/a"). -->

- [ ] `pyproject.toml` `version` bumped and `uv lock` run (the `erdify` entry in `uv.lock` matches)
- [ ] `CHANGELOG.md`: `[Unreleased]` entries moved under `## [X.Y.Z] - YYYY-MM-DD`, an empty `[Unreleased]` kept, compare links updated (`[Unreleased]` and `[X.Y.Z]`)
- [ ] `rev: vX.Y.Z` updated in `.pre-commit-hooks.yaml` and `docs/usage/ci.md`
- [ ] `docs/installation.md` version table matches the CI matrix (if versions changed)
- [ ] No open PR meant for this release; all merged PRs are listed above
- [ ] CI green

## After merge

1. Extract the notes and check they are not empty:
   `awk '/^## \[X\.Y\.Z\]/{f=1;next} /^## \[/{if(f)exit} f' CHANGELOG.md > notes.md && wc -l notes.md`
2. `gh release create vX.Y.Z --target <full SHA of the merge commit> --title vX.Y.Z --notes-file notes.md` (a short SHA is rejected)
3. Approve the gated `pypi` deployment of the `publish.yml` run
4. Check that PyPI serves X.Y.Z (`uvx --no-cache --from erdify==X.Y.Z erdify --version`)
5. Announcement: minor / major releases get one (GitHub Discussions → Announcements); a patch only when it fixes wrong output or a crash for common setups. Planned: yes / no
