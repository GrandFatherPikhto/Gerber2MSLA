# tools/repo_guard.py
"""What a mutation harness may say about the tree it runs in (rule of 25.10, Денис).

A mutation harness runs the cells, and a cell that resolves a config's relative path through
the working directory (a mutant of `config_strict._resolve`) writes its output into whatever
folder pytest was started in — the repository. The cure is in the cells: every cell of a
command line that reads a config works with its working directory inside `tmp_path`
(`_working_directory_inside_tmp` in `tests/test_cli_masks.py` and `tests/test_cli_board.py`).
This module is how a harness SEES that the cure still holds: after every mutation it reads
`git status --porcelain`, and a path that APPEARED is a LEAK — a miss, like a surviving
mutant.

Three rules, all of them learned the hard way:

  * **A dirty tree at the start is normal, not a refusal.** Somebody else's work may be
    lying in the tree — a config, a note, a file being edited right now. The harness
    remembers `before` and judges ONLY what appeared since; refusing to run because of a
    file it did not make is how a run gets blamed for another person's work.
  * **Nothing is deleted.** A guard that tidies up can delete a file that was not junk: the
    leak is reported with its paths, and whoever looks at the report cleans up. Deleting is
    not a harness's business.
  * **A path already in `before` stays forgiven.** It is not a leak now and its later change
    is not a new leak of this mutation either: only a NAME that was not there before counts.

A leak found once is added to `before` by the harness, so the same junk is not blamed on
every following mutation — one leak, one miss, one list of paths.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
"""The repository the harness is testing; a cell points the guard at a throwaway one."""


def changed(root: Path = ROOT) -> set[str]:
    """The paths `git status --porcelain` names, relative to the repository root."""
    result = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                            capture_output=True, text=True)
    return {line[3:].strip() for line in result.stdout.splitlines() if line.strip()}


def leaked(before: set[str], root: Path = ROOT) -> set[str]:
    """Only what APPEARED since `before`: what was already there is nobody's mutation."""
    return changed(root) - before


__all__ = ["ROOT", "changed", "leaked"]
