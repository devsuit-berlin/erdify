---
description: "What erdify's version numbers promise: which surfaces follow semantic versioning, what counts as a breaking change, and how deprecations, Python versions and diagram output changes are handled."
---

# Stability & Versioning

erdify follows [Semantic Versioning](https://semver.org/). From **1.0.0** on:

- **Major** (`2.0.0`): may contain breaking changes, as defined below.
- **Minor** (`1.1.0`): new features and the changes this page explicitly allows
  in a minor release. No breaking changes.
- **Patch** (`1.0.1`): bug fixes only.

Before 1.0.0, a minor release may break things. Every break is listed under
**Changed — breaking** in the [changelog](changelog.md).

## What is covered

| Surface | Stable? | A breaking change is… |
|---|---|---|
| CLI flags | Yes | Removing or renaming a flag, or changing its default. |
| Exit codes | Yes | Changing a code's meaning (see [below](#exit-codes)). |
| `[tool.erdify]` keys | Yes | Removing or renaming a key, or changing its default. |
| pre-commit hook ids (`erdify`, `erdify-check`) | Yes | Removing or renaming an id. |
| Python API (`erdify.__all__`) | Yes, as defined in [What is public](usage/cli.md#what-is-public) | Removing a name, or an incompatible signature change. |
| JSON output | Yes, via `schema_version` | See [JSON compatibility](usage/output-formats.md#compatibility). |
| PlantUML / Mermaid / HTML text | The meaning is stable; the formatting is not | See [below](#diagram-output). |
| Anything else | No | Submodules (`erdify.parser`, …), names starting with `_`, stderr messages, and the HTML page's markup and styling. |

Adding a flag, config key, public name, JSON key or keyword argument with a
default is **not** a breaking change.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Success, or `--check` found everything up to date. |
| `1` | Runtime failure: the input is missing, parsing aborted with an error, no tables were found (without `--allow-empty`), or `--check` found a missing or stale file. |
| `2` | Usage error: invalid or conflicting options. |

A single model or `.sql` file that cannot be parsed (for example, a syntax
error) does **not** fail the run. erdify prints `Error parsing <file>: ...` on
stderr, skips that file and renders the rest, so exit code `0` does not mean
every file was parsed. Check stderr if that matters for you.

### Diagram output

Users who commit the generated diagram and gate CI on `--check` (or the
`erdify-check` hook) see any change in the generated text as a failing check.
erdify therefore separates **what is drawn** from **how it is written**:

- **Stable (major only):** which entities, fields, keys, enums and
  relationships appear, and what they mean. Removing information the diagram
  used to show, or changing a relationship's cardinality without a bug behind
  it, is a breaking change.
- **May change in a minor release:** ordering, whitespace, styling, comments,
  and other formatting that does not change the meaning.

Every minor release that changes the generated text lists it under
**Output changes** in the changelog, because `--check` will fail once after
you upgrade. Regenerate the diagram, commit it, and the check passes again.
To control when that happens, pin erdify: use a lockfile entry, or a `rev:`
for the pre-commit hooks.

A **bug fix** that changes the diagram is not a breaking change, even if it
adds a relationship or key that was missing before, and may ship in a patch
release. It is listed under **Fixed**.

## Deprecations

Before anything public is removed or changed incompatibly, it is deprecated:

1. The changelog lists it under **Deprecated**, with the replacement.
2. Using it emits a `DeprecationWarning` (Python API) or a warning on stderr
   (CLI flags and config keys).
3. It is removed **no earlier than the next major release**.

## Supported Python versions

- New CPython releases are supported in a minor release, usually soon after
  they come out.
- A Python version is dropped **only after CPython has ended support for it**,
  and only in a minor release, never in a patch. `requires-python` is raised at
  the same time, so pip and uv keep resolving the last compatible erdify on the
  old interpreter.

The [installation page](installation.md) lists the currently supported
versions.

## Dependencies

erdify has no runtime dependencies, and that stays true within a major
version. The optional `erdify[sql]` extra depends on `sqlglot`. Widening its
allowed version range can happen in any release. Narrowing it happens only in
a minor release and is listed in the changelog.
