# Configurable Model-File Discovery (`--include`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let erdify discover model files beyond the hardcoded `models.py` via opt-in `--include` glob patterns, with a discreet hint when a `models/` package is ignored.

**Architecture:** Add a glob matcher (stdlib only), thread an `include_patterns` list through `ASTDatabaseParser._discover_model_files` (replacing the hard `"models.py"` check), surface it on the `parse_models_directory` wrapper and the CLI/config, and emit a one-line stderr hint (CLI-only) when a `models/` package is seen under the default.

**Tech Stack:** Python 3.11+, stdlib `os.walk`/`re`/`fnmatch`, argparse, `tomllib` config, pytest.

## Global Constraints

- **Zero runtime dependencies** — stdlib only. No new packages. (`pyproject.toml` `dependencies = []`.)
- **Minimum Python 3.11** — no `PurePath.full_match` (3.13). Implement glob matching by hand.
- **Backward compatible default** — with no `--include`/config, discovery stays exactly `models.py` (recursive, any depth).
- **Replace semantics** — a provided `include` fully replaces the default `["models.py"]`.
- **Library API stays quiet** — `parse_models_directory` emits no hint unless explicitly asked; only the CLI turns it on.
- **mypy strict** + **ruff** (line-length 100) must pass. Docs CLI reference is auto-generated via `python scripts/gen_cli_docs.py`.

---

### Task 1: Glob matcher `_match_include`

**Files:**
- Modify: `src/erdify/parser.py` (add `import re` if missing; add two module-level functions near the top, after the constants block ~line 70)
- Test: `tests/test_include.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `_translate_glob(pattern: str) -> str` — returns a regex string (anchored) for a path glob where `*`/`?` do not cross `/` and `**` crosses segments.
  - `_match_include(rel_path: str, filename: str, patterns: List[str]) -> bool` — `True` if any pattern matches; slash-patterns match `rel_path`, slashless patterns match `filename` (basename, any depth).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_include.py`:

```python
from erdify.parser import _match_include, _translate_glob
import re


def _matches(pattern: str, rel_path: str) -> bool:
    return re.match(_translate_glob(pattern), rel_path) is not None


class TestTranslateGlob:
    def test_star_does_not_cross_slash(self):
        assert _matches("app/*.py", "app/models.py")
        assert not _matches("app/*.py", "app/sub/models.py")

    def test_double_star_crosses_slashes_including_zero(self):
        assert _matches("**/models/*.py", "models/user.py")
        assert _matches("**/models/*.py", "a/b/models/user.py")

    def test_double_star_inner_dir_not_crossed_by_single_star(self):
        # *.py after models/ must not match a nested file
        assert not _matches("**/models/*.py", "models/sub/user.py")

    def test_question_mark_one_non_slash_char(self):
        assert _matches("v?.py", "v1.py")
        assert not _matches("v?.py", "v12.py")


class TestMatchInclude:
    def test_slashless_matches_basename_any_depth(self):
        assert _match_include("a/b/models.py", "models.py", ["models.py"])
        assert _match_include("x/statistics_models.py", "statistics_models.py", ["*_models.py"])

    def test_slashless_does_not_match_other_names(self):
        assert not _match_include("a/tables.py", "tables.py", ["models.py"])

    def test_slash_pattern_matches_relative_path(self):
        assert _match_include("app/models/user.py", "user.py", ["**/models/*.py"])

    def test_no_patterns_no_match(self):
        assert not _match_include("a/models.py", "models.py", [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_include.py -q`
Expected: FAIL with `ImportError: cannot import name '_match_include'`.

- [ ] **Step 3: Implement the matcher**

Confirm `import re` is present at the top of `src/erdify/parser.py` (it currently imports `ast`, `os`, `re`, `sys`). Add after the `DJANGO_FIELD_TYPE_MAP` block (before `class ASTDatabaseParser`):

```python
def _translate_glob(pattern: str) -> str:
    """Compile a gitignore-style path glob to an anchored regex string.

    ``*`` and ``?`` match within a single path segment (never ``/``); ``**``
    matches across segments (zero or more). Python 3.11 has no
    ``PurePath.full_match`` and ``fnmatch`` lets ``*`` cross ``/``, so we
    translate by hand.
    """
    i, n = 0, len(pattern)
    out = ""
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                j = i + 2
                if j < n and pattern[j] == "/":
                    out += "(?:[^/]+/)*"  # **/ -> any number of leading dirs
                    i = j + 1
                else:
                    out += ".*"  # ** -> anything, including /
                    i = j
            else:
                out += "[^/]*"  # * -> within one segment
                i += 1
        elif c == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(c)
            i += 1
    return "(?s:" + out + r")\Z"


def _match_include(rel_path: str, filename: str, patterns: List[str]) -> bool:
    """Whether a file matches any include pattern.

    Slash patterns match the path relative to the input (``rel_path``) with
    ``**`` support; slashless patterns match the ``filename`` basename at any
    depth (so the default ``models.py`` keeps its recursive behavior).
    """
    for pattern in patterns:
        if "/" in pattern:
            if re.match(_translate_glob(pattern), rel_path):
                return True
        elif fnmatchcase(filename, pattern):
            return True
    return False
```

(`fnmatchcase` is already imported at the top of the file.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_include.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add src/erdify/parser.py tests/test_include.py
git commit -m "feat: add gitignore-style glob matcher for model discovery"
```

---

### Task 2: Thread `include_patterns` through discovery

**Files:**
- Modify: `src/erdify/parser.py` — `ASTDatabaseParser.__init__` (~line 76), `_discover_model_files` (~line 102), `parse_models_directory` (~line 997)
- Test: `tests/test_include.py` (append)

**Interfaces:**
- Consumes: `_match_include` (Task 1).
- Produces:
  - `ASTDatabaseParser(..., include_patterns: List[str] | None = None)` → `self.include_patterns` defaults to `["models.py"]`.
  - `parse_models_directory(..., include_patterns: List[str] | None = None)` passes it through.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_include.py`:

```python
from pathlib import Path

from erdify.parser import parse_models_directory

_DC = "from dataclasses import dataclass\n\n\n@dataclass\nclass {name}:\n    id: int\n"


def _make(root: Path, rel: str, name: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_DC.format(name=name))


class TestIncludeDiscovery:
    def test_default_finds_only_models_py(self, tmp_path: Path):
        _make(tmp_path, "app/models.py", "Widget")
        _make(tmp_path, "app/models/order.py", "Order")  # package file: ignored
        entities, _ = parse_models_directory(tmp_path)
        assert "Widget" in entities
        assert "Order" not in entities

    def test_slash_pattern_finds_models_package(self, tmp_path: Path):
        _make(tmp_path, "app/models/order.py", "Order")
        _make(tmp_path, "app/models/user.py", "User")
        entities, _ = parse_models_directory(tmp_path, include_patterns=["**/models/*.py"])
        assert {"Order", "User"} <= set(entities)

    def test_replace_semantics_drops_models_py(self, tmp_path: Path):
        _make(tmp_path, "app/models.py", "Widget")
        _make(tmp_path, "app/tables.py", "Thing")
        entities, _ = parse_models_directory(tmp_path, include_patterns=["tables.py"])
        assert "Thing" in entities
        assert "Widget" not in entities  # models.py no longer matched

    def test_combined_patterns(self, tmp_path: Path):
        _make(tmp_path, "app/models.py", "Widget")
        _make(tmp_path, "app/models/order.py", "Order")
        entities, _ = parse_models_directory(
            tmp_path, include_patterns=["models.py", "**/models/*.py"]
        )
        assert {"Widget", "Order"} <= set(entities)

    def test_exclude_paths_still_applies(self, tmp_path: Path):
        _make(tmp_path, "app/models/order.py", "Order")
        _make(tmp_path, "legacy/models/old.py", "Old")
        entities, _ = parse_models_directory(
            tmp_path, include_patterns=["**/models/*.py"], exclude_paths=["legacy"]
        )
        assert "Order" in entities
        assert "Old" not in entities

    def test_default_dir_pruning_still_applies(self, tmp_path: Path):
        _make(tmp_path, "app/models/order.py", "Order")
        _make(tmp_path, ".venv/lib/models/junk.py", "Junk")
        entities, _ = parse_models_directory(tmp_path, include_patterns=["**/models/*.py"])
        assert "Order" in entities
        assert "Junk" not in entities
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_include.py::TestIncludeDiscovery -q`
Expected: FAIL — `parse_models_directory() got an unexpected keyword argument 'include_patterns'`.

- [ ] **Step 3: Implement — constructor**

In `ASTDatabaseParser.__init__`, add the parameter after `use_default_excludes: bool = True,`:

```python
        use_default_excludes: bool = True,
        include_patterns: List[str] | None = None,
    ):
```

And in the body, after the `self.use_default_excludes = use_default_excludes` line:

```python
        #: Glob patterns selecting which files are scanned; default mirrors the
        #: historical models.py-only behavior. Slash patterns match the path
        #: relative to the input (with **); slashless patterns match basenames.
        self.include_patterns = include_patterns or ["models.py"]
```

- [ ] **Step 4: Implement — discovery loop**

Replace the body of `_discover_model_files` (keep the method name and docstring intro; update it):

```python
    def _discover_model_files(self) -> List[Path]:
        """Find model files, pruning excluded directories during the walk.

        Default-excluded dirs (venv/site-packages/caches) are removed from the
        traversal *before* descending, so large trees like ``.venv`` are never
        scandir'd. A file is selected when it matches ``self.include_patterns``
        (default ``["models.py"]``); ``exclude_paths`` then filters via
        :meth:`_is_path_excluded`. Results are sorted for deterministic output.
        """
        base = self.database_path
        found: List[Path] = []
        for dirpath, dirnames, filenames in os.walk(base):
            if self.use_default_excludes:
                # In-place prune so os.walk does not descend into excluded dirs.
                dirnames[:] = [d for d in dirnames if d not in DEFAULT_EXCLUDE_DIRS]
            dpath = Path(dirpath)
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                candidate = dpath / filename
                try:
                    rel = candidate.relative_to(base).as_posix()
                except ValueError:
                    rel = candidate.as_posix()
                if not _match_include(rel, filename, self.include_patterns):
                    continue
                if not self._is_path_excluded(candidate):
                    found.append(candidate)
        return sorted(found)
```

- [ ] **Step 5: Implement — wrapper**

In `parse_models_directory`, add the parameter after `use_default_excludes: bool = True,`:

```python
    use_default_excludes: bool = True,
    include_patterns: List[str] | None = None,
) -> Tuple[Dict[str, EntityInfo], Dict[str, EnumInfo]]:
```

Add to the docstring Args (after the `use_default_excludes:` entry):

```python
        include_patterns: Glob patterns selecting which files are scanned.
            Slash patterns match the path relative to ``path`` (``**`` crosses
            dirs); slashless patterns match a basename at any depth. Defaults to
            ``["models.py"]``.
```

And pass it into the constructor call (after `use_default_excludes=use_default_excludes,`):

```python
        use_default_excludes=use_default_excludes,
        include_patterns=include_patterns,
    )
```

- [ ] **Step 6: Run tests + regression suite**

Run: `.venv/bin/python -m pytest tests/test_include.py tests/test_scan_filter.py -q`
Expected: PASS (all). Then `.venv/bin/python -m pytest -q` → 234+ passed.

- [ ] **Step 7: Lint + types**

Run: `.venv/bin/ruff check src tests && .venv/bin/mypy src`
Expected: `All checks passed!` and `Success: no issues found`.

- [ ] **Step 8: Commit**

```bash
git add src/erdify/parser.py tests/test_include.py
git commit -m "feat: select model files via include_patterns (default models.py)"
```

---

### Task 3: `models/` package hint (parser side)

**Files:**
- Modify: `src/erdify/parser.py` — `__init__`, `_discover_model_files`, `parse_models_directory`
- Test: `tests/test_include.py` (append)

**Interfaces:**
- Consumes: discovery from Task 2.
- Produces:
  - `ASTDatabaseParser(..., hint_unmatched_model_packages: bool = False)`.
  - `parse_models_directory(..., hint_unmatched_model_packages: bool = False)`.
  - Behavior: when the flag is set and a directory named `models` containing ≥1 `.py` is walked, one line is printed to **stderr**.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_include.py`:

```python
class TestModelsPackageHint:
    def test_hint_emitted_when_default_and_package_present(self, tmp_path, capsys):
        _make(tmp_path, "app/models.py", "Widget")
        _make(tmp_path, "app/models/order.py", "Order")
        parse_models_directory(tmp_path, hint_unmatched_model_packages=True)
        err = capsys.readouterr().err
        assert "models/" in err and "--include" in err

    def test_no_hint_when_flag_off(self, tmp_path, capsys):
        _make(tmp_path, "app/models/order.py", "Order")
        parse_models_directory(tmp_path)  # library default: silent
        assert capsys.readouterr().err == ""

    def test_no_hint_when_no_package(self, tmp_path, capsys):
        _make(tmp_path, "app/models.py", "Widget")
        parse_models_directory(tmp_path, hint_unmatched_model_packages=True)
        assert capsys.readouterr().err == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_include.py::TestModelsPackageHint -q`
Expected: FAIL — unexpected keyword `hint_unmatched_model_packages`.

- [ ] **Step 3: Implement — constructor**

Add the parameter after `include_patterns: List[str] | None = None,`:

```python
        include_patterns: List[str] | None = None,
        hint_unmatched_model_packages: bool = False,
    ):
```

In the body, after `self.include_patterns = ...`:

```python
        #: When True, warn (once, on stderr) about a models/ package that the
        #: current include patterns skip. The CLI sets this only at the default;
        #: the library stays silent so programmatic callers get no stderr noise.
        self.hint_unmatched_model_packages = hint_unmatched_model_packages
        self._unmatched_model_packages: List[Path] = []
```

- [ ] **Step 4: Implement — record + emit in `_discover_model_files`**

Inside the `os.walk` loop, right after `dpath = Path(dirpath)`:

```python
            dpath = Path(dirpath)
            if (
                self.hint_unmatched_model_packages
                and dpath.name == "models"
                and any(f.endswith(".py") for f in filenames)
            ):
                self._unmatched_model_packages.append(dpath)
```

And before `return sorted(found)`:

```python
        if self._unmatched_model_packages:
            example = sorted(self._unmatched_model_packages)[0]
            print(
                f"Hint: found a models/ package ({example}) that was not scanned "
                f"(the default only matches models.py). Use "
                f"--include '**/models/*.py' to include it.",
                file=sys.stderr,
            )
        return sorted(found)
```

(`sys` is already imported.)

- [ ] **Step 5: Implement — wrapper**

In `parse_models_directory`, add the parameter after `include_patterns: List[str] | None = None,`:

```python
    include_patterns: List[str] | None = None,
    hint_unmatched_model_packages: bool = False,
) -> Tuple[Dict[str, EntityInfo], Dict[str, EnumInfo]]:
```

Pass it into the constructor (after `include_patterns=include_patterns,`):

```python
        include_patterns=include_patterns,
        hint_unmatched_model_packages=hint_unmatched_model_packages,
    )
```

- [ ] **Step 6: Run tests + suite + lint**

Run: `.venv/bin/python -m pytest tests/test_include.py -q && .venv/bin/python -m pytest -q`
Expected: PASS. Then `.venv/bin/ruff check src tests && .venv/bin/mypy src` → clean.

- [ ] **Step 7: Commit**

```bash
git add src/erdify/parser.py tests/test_include.py
git commit -m "feat: hint about ignored models/ packages (opt-in, stderr)"
```

---

### Task 4: CLI flag, config key, and hint wiring

**Files:**
- Modify: `src/erdify/cli.py` — add `--include` argument (~after the `--sources` block, line ~88), resolve via `pick`, compute the hint flag, pass both into `parse_models_directory` (~line 206)
- Modify: `src/erdify/pyproject.py` — add `"include"` to `CONFIG_KEYS` (~line 14)
- Test: `tests/test_cli.py` (append)

**Interfaces:**
- Consumes: `parse_models_directory(..., include_patterns=..., hint_unmatched_model_packages=...)` (Tasks 2–3).
- Produces: `erdify --include PATTERN ...` and `[tool.erdify] include = [...]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`. `main()` takes **no** arguments — it reads
`sys.argv`, so patch it exactly like the existing tests in this file
(`with patch.object(sys, "argv", [...])`). The file already imports `sys`,
`patch` (from `unittest.mock`), and `main`.

```python
_DC_CLI = "from dataclasses import dataclass\n\n\n@dataclass\nclass {name}:\n    id: int\n"


def test_include_flag_finds_models_package(tmp_path, capsys):
    (tmp_path / "app" / "models").mkdir(parents=True)
    (tmp_path / "app" / "models" / "order.py").write_text(_DC_CLI.format(name="Order"))
    with patch.object(sys, "argv", ["erdify", str(tmp_path), "--include", "**/models/*.py"]):
        rc = main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "Order" in out


def test_include_config_key(tmp_path, capsys):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "user.py").write_text(_DC_CLI.format(name="User"))
    (tmp_path / "pyproject.toml").write_text('[tool.erdify]\ninclude = ["**/models/*.py"]\n')
    with patch.object(sys, "argv", ["erdify", str(tmp_path)]):
        rc = main()
    assert rc == 0
    assert "User" in capsys.readouterr().out
```

If `tests/test_cli.py` does not already import `sys`/`patch`/`main` at module
level, add `import sys`, `from unittest.mock import patch`, and
`from erdify.cli import main` (matching the existing style at the top of the file).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k include -q`
Expected: FAIL — `--include` unrecognized / `Order` not in output.

- [ ] **Step 3: Add the CLI argument**

In `src/erdify/cli.py`, after the `--sources` `add_argument` block, insert:

```python
    parser.add_argument(
        "--include",
        nargs="*",
        default=None,
        metavar="PATTERN",
        help=(
            "Glob patterns for files to scan (default: models.py). A pattern "
            "with '/' matches the path relative to input ('**' crosses dirs); a "
            "pattern without '/' matches a filename at any depth. Replaces the "
            "default, so list models.py too if you want it, e.g. --include "
            "models.py '**/models/*.py' tables.py"
        ),
    )
```

- [ ] **Step 4: Resolve include + hint flag and pass through**

In `main`, alongside the other `pick(...)` lines (after `exclude_paths = pick(...)`):

```python
    include = pick(args.include, "include", ["models.py"])
    # Hint only when the user left discovery at the default (neither CLI nor config).
    include_is_default = args.include is None and "include" not in config
```

Then extend the `parse_models_directory(...)` call (after `use_default_excludes=not no_default_excludes,`):

```python
            use_default_excludes=not no_default_excludes,
            include_patterns=include,
            hint_unmatched_model_packages=include_is_default,
        )
```

- [ ] **Step 5: Add the config key**

In `src/erdify/pyproject.py`, add `"include"` to the `CONFIG_KEYS` frozenset (next to `"exclude_paths"`):

```python
        "exclude",
        "exclude_paths",
        "include",
```

- [ ] **Step 6: Run tests + suite + lint**

Run: `.venv/bin/python -m pytest tests/test_cli.py -k include -q && .venv/bin/python -m pytest -q`
Expected: PASS. Then `.venv/bin/ruff check src tests && .venv/bin/mypy src` → clean.

- [ ] **Step 7: Commit**

```bash
git add src/erdify/cli.py src/erdify/pyproject.py tests/test_cli.py
git commit -m "feat: --include CLI flag and [tool.erdify] include key"
```

---

### Task 5: Docs + changelog

**Files:**
- Modify: `docs/usage/filtering.md` (add a discovery section)
- Modify: `docs/usage/cli.md` (regenerated, not hand-edited)
- Modify: `CHANGELOG.md` (`[Unreleased]`)

**Interfaces:**
- Consumes: the shipped `--include` flag + `include` config key.
- Produces: published docs + changelog entry.

- [ ] **Step 1: Add a discovery section to `docs/usage/filtering.md`**

Insert a new section before `## Excluding Entities` (so "what is scanned" precedes "what is removed"):

```markdown
## Choosing Which Files Are Scanned (`--include`)

By default erdify scans every file named `models.py` (at any depth). To scan
other files — a `models/` package, or files like `tables.py`/`db.py` — pass
`--include` with one or more glob patterns:

```bash
# A models/ package split across files
erdify ./app --include '**/models/*.py'

# Keep models.py AND add a package and a custom file
erdify ./app --include models.py '**/models/*.py' tables.py
```

Pattern rules:

- A pattern **with `/`** (e.g. `**/models/*.py`, `app/db.py`) matches the path
  relative to the input. `**` crosses directories; `*` and `?` do not cross `/`.
- A pattern **without `/`** (e.g. `models.py`, `*_models.py`) matches a
  **filename at any depth**.

`--include` **replaces** the default, so include `models.py` explicitly if you
still want it. Equivalent `[tool.erdify]` config:

```toml
[tool.erdify]
include = ["models.py", "**/models/*.py"]
```

If erdify sees a `models/` package while running with the default, it prints a
one-line hint suggesting `--include '**/models/*.py'`.
```

(Note: the triple-backtick fences inside the doc are real fenced blocks — keep them.)

- [ ] **Step 2: Regenerate the CLI reference**

Run: `.venv/bin/python scripts/gen_cli_docs.py`
Expected: rewrites the `cli-help` block in `docs/usage/cli.md` to include `--include`. Verify with `.venv/bin/python scripts/gen_cli_docs.py --check` → exit 0.

- [ ] **Step 3: Add the changelog entry**

In `CHANGELOG.md`, under `## [Unreleased]`, add:

```markdown
## [Unreleased]

### Added

- `--include` — scan model files beyond `models.py` via glob patterns (e.g.
  `--include '**/models/*.py' tables.py`). Patterns with `/` match the path
  relative to the input (`**` crosses directories); patterns without `/` match a
  filename at any depth. `--include` replaces the default `models.py`, and is
  also settable as `include` in `[tool.erdify]`. When run at the default, erdify
  now hints (once, on stderr) about a `models/` package it skipped.
```

- [ ] **Step 4: Verify docs build and nothing is stale**

Run: `.venv/bin/python scripts/gen_cli_docs.py --check && .venv/bin/python -m pytest -q`
Expected: exit 0 and full suite green.

- [ ] **Step 5: Commit**

```bash
git add docs/usage/filtering.md docs/usage/cli.md CHANGELOG.md
git commit -m "docs: document --include discovery and changelog entry"
```

---

## Self-Review

**Spec coverage:**
- §1 CLI & config → Task 4. ✓
- §2 matching semantics → Task 1. ✓
- §3 discovery flow → Task 2. ✓
- §4 models/ hint → Task 3 (parser) + Task 4 (CLI wiring of the default flag). ✓
- §5 tests → distributed across Tasks 1–4 (matcher unit, discovery, hint, CLI/config). ✓
- §6 docs → Task 5. ✓
- Out-of-scope items are not implemented (no auto-detect, no per-source defaults, no regex). ✓

**Placeholder scan:** No TBD/TODO; all code steps show full code; the only conditional ("mirror test_cli.py's runner style") names the exact assertions to keep. ✓

**Type consistency:** `include_patterns: List[str] | None` and `hint_unmatched_model_packages: bool` are used identically in `ASTDatabaseParser.__init__`, `parse_models_directory`, and the CLI call. `_match_include(rel_path, filename, patterns)` signature matches every call site. ✓
