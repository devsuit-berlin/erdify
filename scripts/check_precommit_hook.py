"""Exercise the pre-commit hooks of .pre-commit-hooks.yaml as a user's project would (#269).

Builds a throwaway git project (the ``ecommerce`` fixture's models and a
``[tool.erdify]`` config) whose ``.pre-commit-config.yaml`` points at this
checkout, pinned to a commit like a user's config pins a tag. pre-commit then
installs erdify from it into its own environment and runs the hooks:

1. ``erdify`` writes the missing diagram (pre-commit passes: it only flags
   changes to tracked files), and passes again once it is committed;
2. the diagram ends with exactly one newline, and ``erdify-check`` passes on
   it, on a file without one (an older erdify) and on one with it added
   (what pre-commit's ``end-of-file-fixer`` leaves; simulated, not run);
3. after a model change, ``erdify-check`` fails without writing anything, and
   ``erdify`` regenerates the diagram so the check passes again;
4. neither hook runs for a change to a file that is no ``models.py``.

Usage (needs git; pre-commit installs erdify, so the network is used)::

    uv run --group hooks python scripts/check_precommit_hook.py [REF]

``REF`` is the commit to install, ``HEAD`` by default: commit your changes
first, uncommitted ones are not part of it. pre-commit (the ``hooks``
dependency group in ``uv.lock``) keeps its environments in the temporary
directory, so nothing is left behind and every run installs afresh.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "tests" / "fixtures" / "ecommerce" / "models.py"
DIAGRAM = "docs/erd.puml"

PYPROJECT = """\
[project]
name = "shop"
version = "0"

[tool.erdify]
title = "Shop ERD"
output = "docs/erd.puml"
"""

CONFIG = """\
repos:
  - repo: {repo}
    rev: {rev}
    hooks:
      - id: erdify
        args: [app]
      - id: erdify-check
        args: [app]
"""


ENV = {
    k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")
}


def run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=ENV)


def git(project: Path, *args: str) -> None:
    result = run(project, "git", *args)
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr}")


def hook(project: Path, hook_id: str, *files: str) -> subprocess.CompletedProcess[str]:
    selection = ["--files", *files] if files else ["--all-files"]
    return run(
        project, sys.executable, "-m", "pre_commit", "run", "--color=never", hook_id, *selection
    )


def expect(result: subprocess.CompletedProcess[str], code: int, step: str) -> None:
    if result.returncode != code:
        print(result.stdout, result.stderr, sep="\n", file=sys.stderr)
        raise SystemExit(f"FAIL: {step}: exit {result.returncode}, expected {code}")
    print(f"ok: {step}")


def commit(project: Path, message: str) -> None:
    git(project, "add", "-A")
    # --no-verify: the developer's own git hooks must not run in the sample.
    git(project, "commit", "-q", "--no-verify", "--allow-empty", "-m", message)


def main(argv: list[str]) -> int:
    ref = argv[0] if argv else "HEAD"
    rev = subprocess.run(
        ["git", "rev-parse", ref], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    with tempfile.TemporaryDirectory() as tmp:
        # Hook environments live here too, not in the user's ~/.cache/pre-commit.
        ENV["PRE_COMMIT_HOME"] = str(Path(tmp) / "pre-commit-home")
        project = Path(tmp) / "shop"
        (project / "app").mkdir(parents=True)
        shutil.copy(MODELS, project / "app" / "models.py")
        (project / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
        (project / "README.md").write_text("# Shop\n", encoding="utf-8")
        config = CONFIG.format(repo=ROOT.as_posix(), rev=rev)
        (project / ".pre-commit-config.yaml").write_text(config, encoding="utf-8")
        for args in (
            # No template hooks (e.g. a global pre-commit init-templatedir).
            ("-c", "init.templateDir=", "init", "-q"),
            ("config", "core.hooksPath", "/dev/null"),
            ("config", "user.email", "ci@example.invalid"),
            ("config", "user.name", "CI"),
            ("config", "commit.gpgsign", "false"),
        ):
            git(project, *args)
        commit(project, "models")
        diagram = project / DIAGRAM

        # 1. The erdify hook writes the missing diagram. pre-commit only flags
        # changes to tracked files, so creating a new one passes.
        expect(hook(project, "erdify"), 0, "erdify writes the missing diagram")
        if not diagram.exists() or "Shop ERD" not in diagram.read_text(encoding="utf-8"):
            raise SystemExit(f"FAIL: {DIAGRAM} not written with the [tool.erdify] title")
        commit(project, "diagram")
        expect(hook(project, "erdify"), 0, "erdify passes once the diagram is committed")

        # 2. One trailing newline; erdify-check passes with or without it.
        written = diagram.read_text(encoding="utf-8")
        if not written.endswith("\n") or written.endswith("\n\n"):
            raise SystemExit("FAIL: the diagram does not end with exactly one newline")
        print("ok: the diagram ends with one newline")
        expect(hook(project, "erdify-check"), 0, "erdify-check passes on the committed diagram")
        text = diagram.read_text(encoding="utf-8").rstrip("\n")
        for ending, origin in (("", "an older erdify"), ("\n", "end-of-file-fixer")):
            diagram.write_text(text + ending, encoding="utf-8")
            commit(project, origin)
            expect(hook(project, "erdify-check"), 0, f"erdify-check passes on a file from {origin}")

        # 3. A model change: the check fails and writes nothing; erdify regenerates.
        models = project / "app" / "models.py"
        models.write_text(
            models.read_text(encoding="utf-8")
            + "\n\nclass Coupon(SQLModel, table=True):\n"
            + "    id: int | None = Field(default=None, primary_key=True)\n"
            + "    code: str\n",
            encoding="utf-8",
        )
        commit(project, "new model")
        before = diagram.read_text(encoding="utf-8")
        expect(hook(project, "erdify-check"), 1, "erdify-check fails after a model change")
        if diagram.read_text(encoding="utf-8") != before:
            raise SystemExit("FAIL: erdify-check wrote the diagram")
        expect(hook(project, "erdify"), 1, "erdify regenerates the stale diagram")
        if "Coupon" not in diagram.read_text(encoding="utf-8"):
            raise SystemExit("FAIL: the regenerated diagram lacks the new model")
        commit(project, "regenerated diagram")
        expect(hook(project, "erdify-check"), 0, "erdify-check passes again")

        # 4. The hooks only run for models.py changes.
        for hook_id in ("erdify", "erdify-check"):
            result = hook(project, hook_id, "README.md")
            expect(result, 0, f"{hook_id} is skipped for a non-model file")
            if "(no files to check)Skipped" not in result.stdout:
                print(result.stdout, file=sys.stderr)
                raise SystemExit(f"FAIL: {hook_id} ran for README.md")
    print(f"The pre-commit hooks work (erdify at {rev[:12]}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
