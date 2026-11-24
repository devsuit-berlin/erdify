# Arrange with erdify-studio

erdify always lays diagrams out automatically. When you want a hand-made layout that
survives schema changes, use [erdify-studio](https://erdify-studio.devsuit.io/), a
separate package built on erdify:

- **Drag and drop** the entities of your erdify diagrams in the browser. The canvas runs
  on `127.0.0.1` only, with no Node, database or browser engine to install.
- **Commit the layout** as a file next to your code, so it's shared through git.
- **Check it in CI** and pre-commit: `erdify-studio check` fails when the layout is out
  of date, the same way `erdify --check` does for a committed diagram.
- **Place new tables** automatically (`erdify-studio place --auto`), and **export** one
  SVG per diagram.

It reads the same sources and options as erdify (`[tool.erdify]` in `pyproject.toml`),
plus a `[tool.erdify-studio]` section, and draws erdify's own entities and edges.

```bash
pip install erdify-studio          # or: pip install "erdify-studio[sql]" for SQL DDL
erdify-studio                      # open the canvas, drag, save
erdify-studio check                # exit 1 if the committed layout is out of date
```

erdify-studio is in **alpha**. See its [documentation](https://erdify-studio.devsuit.io/)
for the canvas, the layout file and the CI setup.
