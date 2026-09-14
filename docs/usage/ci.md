# CI/CD & pre-commit

Keep your ERD diagrams automatically up to date in continuous integration and on every commit.

## Integration with CI/CD

### Gate on drift (recommended)

The strongest thing CI can do is **fail** when the committed diagram no longer
matches the models. `--check` regenerates in memory, compares, and writes
nothing:

```yaml
# .github/workflows/erd.yml
name: ERD

on: pull_request

jobs:
  erd-up-to-date:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Check the ERD is up to date
        run: pipx run erdify ./src/database --title "Database Schema" -o docs/erd.puml --check
```

A stale diagram fails the pull request; the contributor re-runs erdify locally
and commits the regenerated file, so the change to the schema **and** the change
to the diagram are reviewed together. That is the behavior you usually want:
the diagram is documentation, and documentation should go through review.

`--check` validates every `--format` target, and works the same way for an
[injected Markdown diagram](#keeping-an-embedded-readme-diagram-fresh).

### Alternative: regenerate and commit

If you would rather have CI keep the diagram current by itself, generate it and
push the result back. The trade-off: the diagram lands on your default branch
without review, and a misconfigured run can commit an empty or wrong diagram
over a good one.

```yaml
# .github/workflows/erd.yml
name: Generate ERD

on:
  push:
    paths:
      - 'src/database/**'

jobs:
  generate-erd:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install erdify
        run: pip install erdify        # use 'erdify[sql]' for SQL DDL projects

      - name: Generate ERD
        run: erdify ./src/database --title "Database Schema" -o docs/erd.puml

      - name: Generate PNG
        run: |
          sudo apt-get install -y plantuml
          plantuml docs/erd.puml

      - name: Commit changes
        uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "docs: update ERD diagram"
          file_pattern: "docs/erd.*"
```

### SQL DDL projects

For projects that generate the ERD from `.sql` files, install `erdify[sql]` and
trigger on `*.sql` paths:

```yaml
      - name: Install erdify (SQL)
        run: pip install 'erdify[sql]'

      - name: Generate ERD from SQL
        run: erdify ./schema --include '*.sql' --sql-dialect postgres -o docs/erd.puml
```

Or with uvx:

```bash
uvx --from 'erdify[sql]' erdify ./schema --include '*.sql' --sql-dialect postgres -o docs/erd.puml
```

!!! note "About the unpinned actions in these examples"

    The workflow snippets on this page use floating tags (`actions/checkout@v4`)
    for readability. erdify's own workflows pin every action to a full commit
    SHA, and **you should too** in a repository you control — a moving tag is a
    supply-chain risk that a SHA removes. Pinning here would mean shipping SHAs
    that go stale in the docs; pin them when you copy the snippet:

    ```yaml
    - uses: actions/checkout@<full-sha>  # v4.x
    ```

## Integration with pre-commit hooks

erdify ships its own [pre-commit](https://pre-commit.com/) hooks. You do not have
to install erdify into your project first — pre-commit builds an isolated
environment for it:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/devsuit-berlin/erdify
    rev: v0.12.3
    hooks:
      - id: erdify
        args: [./src/database, -o, docs/erd.puml]
```

`args` is required: erdify needs to know which directory (or file) to read
models from. Everything else — title, filters, format — can also live in
`[tool.erdify]` in your `pyproject.toml`.

### The two hook ids

| id | Behavior | Use it for |
| --- | --- | --- |
| `erdify` | Regenerates the diagram. pre-commit fails the commit when the file changed; stage the regenerated diagram and commit again. | Keeping the committed diagram in sync automatically. |
| `erdify-check` | Never writes. Exits non-zero when the committed diagram no longer matches the models. | A read-only drift gate, e.g. `pre-commit run erdify-check --all-files` in CI. |

`--check` is part of `erdify-check`'s entry point, so overriding `args` cannot
accidentally drop it.

Both hooks run when a staged file matches `(^|/)models\.py$`, which mirrors
erdify's default `--include models.py`. Override `files` when your models live
elsewhere:

```yaml
      - id: erdify
        args: [./src/database, --include, 'models.py', 'schema.py', -o, docs/erd.puml]
        files: ^src/database/.*\.py$
```

### SQL DDL projects

There is deliberately no separate hook id for SQL. The `erdify[sql]` extra only
adds the `sqlglot` runtime dependency, so pull that into the hook environment
instead:

```yaml
      - id: erdify
        alias: erdify-sql
        args: [./schema, --include, '*.sql', --sql-dialect, postgres, -o, docs/erd.puml]
        files: ^schema/.*\.sql$
        additional_dependencies: ['sqlglot>=25']
```

Use `alias` when you want both a Python-model and a SQL hook in the same config,
so `pre-commit run <id>` can address them separately.

### Alternative: erdify already installed in your environment

If erdify is a dependency of your project (or available via `uvx`), a `local`
hook avoids the second environment:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: generate-erd
        name: Generate ERD diagram
        entry: erdify ./src/database --title "Database Schema" -o docs/erd.puml
        language: system
        files: ^src/database/.*\.py$
        pass_filenames: false
```

Or using uvx (no installation required):

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: generate-erd
        name: Generate ERD diagram
        entry: uvx erdify ./src/database --title "Database Schema" -o docs/erd.puml
        language: system
        files: ^src/database/.*\.py$
        pass_filenames: false
```

The trade-off: `language: system` runs whatever `erdify` resolves to on that
machine, so the version is not pinned by `rev` and contributors can silently
produce different output.

**Setup:**

```bash
# Install pre-commit
pip install pre-commit

# Install the hooks
pre-commit install

# Run manually on all files
pre-commit run erdify --all-files
```

**How it works:**

- Only triggers when files matching the hook's `files` pattern change
- Regenerates `docs/erd.puml` on commit
- If the diagram changed, pre-commit reports the modified file and fails the
  commit — stage the regenerated diagram and commit again to keep docs in sync

## Keeping an embedded README diagram fresh

If you embed the ERD in a markdown file with `--inject`, gate it in CI the same
way as a file output:

```bash
erdify ./db --inject README.md --check
```

This exits non-zero when the diagram between the markers is stale, so a forgotten
regeneration fails the build instead of silently shipping an outdated diagram.
