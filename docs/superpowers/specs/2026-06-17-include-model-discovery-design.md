# Design: configurable model-file discovery (`--include`)

**Date:** 2026-06-17
**Status:** Approved

## Problem

erdify discovers model files by matching the **exact filename `models.py`**
(`parser.py`: `"models.py" in filenames`). This misses two common Python layouts:

- **`models/` packages** — larger Django/SQLModel apps split models across
  `models/user.py`, `models/order.py`, etc. None are found.
- **Differently-named files** — `tables.py`, `db.py`, `schema.py`,
  `*_models.py`.

This is the single largest functional limitation for adoption beyond projects
that centralize in `models.py`. (Note: it does not currently affect the
in-house eattaxi/bastuck repos, which centralize in `models.py`.)

## Decision summary

- **A + C**: keep the default strictly `models.py` (opt-in broadening), plus a
  discreet one-line hint when a `models/` package is detected but ignored.
- Mechanism: a new `--include` option taking **glob patterns**, with
  **replace** semantics (when set, it fully replaces the default).
- Patterns settable in `[tool.erdify]` via an `include` list, with the standard
  precedence **CLI flag > config > default `["models.py"]`**.

## 1. CLI & config

- New option: `--include PATTERN [PATTERN ...]` (`nargs="*"`, `default=None`,
  `metavar="PATTERN"`).
- New recognized `[tool.erdify]` key: `include` (list of strings) — add to
  `CONFIG_KEYS` in `pyproject.py`.
- Resolution reuses the existing `pick` helper in `cli.py`:
  `include = pick(args.include, "include", ["models.py"])`.
- **Replace semantics**: a non-`None` value fully replaces the default. To keep
  `models.py` *and* add a package, the user lists both:
  `--include models.py '**/models/*.py'`. (Mirrors `--sources`, which restricts
  rather than extends.)

## 2. Matching semantics (gitignore-style, backward compatible)

Each candidate file is tested against the include patterns:

- **Pattern without `/`** (e.g. `models.py`, `*_models.py`) → matches the file's
  **basename at any depth**. This makes the default `models.py` behave exactly
  as today (recursive match at any depth).
- **Pattern with `/`** (e.g. `models/*.py`, `app/db.py`, `**/models/*.py`) →
  matches the **path relative to the input directory** (posix). `**` crosses
  directory boundaries; `*` and `?` do **not** cross `/`.

Matching is case-sensitive, consistent with `--exclude` / `--exclude-paths`.

A small helper translates a glob to a regex (stdlib only — Python 3.11 has no
`PurePath.full_match`, and `fnmatch` lets `*` cross `/`, which we must not
allow for slash patterns):

- `_match_include(rel_posix_path: str, filename: str, patterns: list[str]) -> bool`
- For each pattern: if it contains `/`, match against `rel_posix_path` with the
  glob→regex translation (with `**` support); otherwise match `filename` with
  `fnmatchcase`.

`__init__.py` is **not** special-cased: a pattern like `**/models/*.py` will
match `models/__init__.py`, erdify parses it, and if it defines no models it
yields no entities. Harmless, keeps the rule simple.

## 3. Discovery flow (`ASTDatabaseParser._discover_model_files`)

The existing structure is preserved; only file selection changes:

1. `os.walk` with default-exclude-dir pruning (the perf behavior shipped in
   0.8.0 — unchanged).
2. A file becomes a candidate when its (relative path, basename) matches any
   `include` pattern (replacing the hard `== "models.py"` check).
3. `_is_path_excluded` (exclude_paths globs + default-dir segment safety net)
   filters as before.
4. Results are `sorted()` (deterministic — unchanged).

New constructor parameter `include_patterns: List[str] | None = None`,
defaulting to `["models.py"]`, threaded through the `parse_models_directory`
wrapper.

## 4. `models/` package hint (part C)

- Fires **only when `include` is at its default** (`["models.py"]`). The CLI
  knows whether the value came from the default and passes a flag into the
  parser; the library API leaves it off.
- During the same walk, record any directory whose name is exactly `models`
  that contains at least one `.py` file. (In default mode such files never match
  `models.py`, so the package is genuinely unscanned — no further check needed.)
- After discovery, emit **one** line to stderr, e.g.:
  > `Hint: found a models/ package that was not scanned (the default only
  > matches models.py). Use --include '**/models/*.py' to include it.`
- **Library API (`parse_models_directory`) stays silent by default** — a new
  parameter `hint_unmatched_model_packages: bool = False`; the CLI sets it
  `True` only when `include` is at default. No stderr surprises for programmatic
  callers.
- On stderr, so it never pollutes `--check` / piped stdout output.

## 5. Tests (TDD)

Parser / discovery (`tests/test_scan_filter.py` or a new `test_include.py`):

- **Backward compat**: with no `include`, only `models.py` files are found.
- **Slash pattern**: `include=['**/models/*.py']` finds files in a `models/`
  package; `models.py` is no longer found (replace semantics).
- **No-slash suffix**: `include=['*_models.py']` matches by basename at any
  depth.
- **Combined**: `include=['models.py', '**/models/*.py']` finds both.
- **exclude_paths still applies** on top of include.
- **Default-dir pruning still applies** (a `.venv` subtree is not scanned) even
  with a custom include.
- **Config**: `include` in `[tool.erdify]` is honored; an explicit `--include`
  overrides the config value.
- **Hint**: emitted to stderr when a `models/` package exists and `include` is
  default; **not** emitted when `include` is customized or no `models/` package
  is present; **not** emitted by `parse_models_directory` by default.

Unit (`_match_include`):

- `**` crosses directories; `*`/`?` do not cross `/`; no-slash patterns match
  basename at any depth; case sensitivity.

## 6. Docs (in-scope, not an afterthought)

- `docs/usage/filtering.md`: new section **"Which files are scanned
  (`--include`)"** — patterns, the slash/no-slash rule, replace semantics,
  `models/`-package and `tables.py` examples, and the `[tool.erdify]` `include`
  key.
- `docs/usage/cli.md`: auto-regenerated from `erdify --help` by the existing
  pre-commit hook — so the `--include` help text must be self-explanatory.
- Wherever `[tool.erdify]` keys are listed, add `include`.
- `CHANGELOG.md`: an `### Added` entry under `[Unreleased]`.

## Out of scope (YAGNI)

- No auto-detection of `models/` packages by default (that is the rejected
  option B — only the opt-in flag plus the hint).
- No per-source default patterns (e.g. Django-specific discovery). One uniform
  `include` mechanism.
- No regex patterns — globs only.
