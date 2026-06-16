# CI/CD & pre-commit

Keep your ERD diagrams automatically up to date in continuous integration and on every commit.

## Integration with CI/CD

```yaml
# .github/workflows/docs.yml
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
        run: pip install erdify

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

## Integration with pre-commit hooks

Keep your ERD diagrams automatically updated on every commit using [pre-commit](https://pre-commit.com/):

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: generate-erd
        name: 🗃️ Generate ERD Diagram
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
        name: 🗃️ Generate ERD Diagram
        entry: uvx erdify ./src/database --title "Database Schema" -o docs/erd.puml
        language: system
        files: ^src/database/.*\.py$
        pass_filenames: false
```

**Setup:**

```bash
# Install pre-commit
pip install pre-commit

# Install the hooks
pre-commit install

# Run manually on all files
pre-commit run generate-erd --all-files
```

**How it works:**
- 🔍 Only triggers when files in `src/database/` change
- 📝 Automatically regenerates `docs/erd.puml`
- ✅ Stages the updated diagram with your commit
- 🚫 Fails if the diagram would change (ensuring docs stay in sync)

**Tip:** Add `docs/erd.puml` to your staged files before committing, or use the `--all-files` flag to regenerate.
