# `badges` branch

Machine-written branch. Do not develop here and do not merge it anywhere.

It holds the shields.io endpoint payload behind the coverage badge in the
README on `main`:

```
https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/devsuit-berlin/erdify/badges/coverage.json
```

The `Coverage badge` job in `.github/workflows/test.yml` rewrites
`coverage.json` on every push to `main` and commits it here as
`github-actions[bot]`, using the workflow's built-in `GITHUB_TOKEN`.

It lives on an orphan branch on purpose:

- the repository owns the badge data — no personal access token and no
  third-party service is involved, so nothing breaks when a contributor leaves;
- the bot commits stay out of the `main` history;
- pushes made with `GITHUB_TOKEN` do not trigger workflows, so there is no
  build loop.
