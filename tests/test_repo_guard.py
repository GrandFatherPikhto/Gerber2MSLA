"""`tools/repo_guard.py` — what a mutation harness may say about the tree (rule of 25.10).

Cells closed here:

    новое          путь, появившийся после `before`, — LEAK; тот, что был до прогона, — нет
    не удаляет     сторож НИЧЕГО не удаляет: чужой неотслеживаемый файл на месте и не
                   изменился, а функции удаления у него нет вовсе
    чужое грязное  грязное дерево на старте — норма: файл, изменённый до прогона, не
                   становится «мусором мутанта»

The guard is a diagnostics tool in `tools/`, so a cell loads it BY PATH: `import repo_guard`
would need that folder on `sys.path`, and a test that depends on where a harness happens to
be started is a test that lies. The repository is a throwaway one, `git init`ed in
`tmp_path`: a cell must never make the real tree dirty, and the guard is exercised on paths
it did not make.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

GUARD = Path(__file__).resolve().parents[1] / "tools" / "repo_guard.py"


def _guard():
    """The module, loaded from its file: the tool is not a package and must not be one."""
    spec = importlib.util.spec_from_file_location("repo_guard_for_cells", GUARD)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repo(folder: Path) -> Path:
    """A throwaway repository with one staged file — enough for `git status` to speak."""
    subprocess.run(["git", "init", "-q", str(folder)], check=True)
    (folder / "tracked.txt").write_text("a line\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=folder, check=True,
                   capture_output=True)
    return folder


def test_only_a_path_that_appeared_is_a_leak(tmp_path):
    """`before` is remembered; exactly the new name comes back, and nothing else."""
    guard = _guard()
    repo = _repo(tmp_path)
    (repo / "notes.toml").write_text("# Denis's file, being edited\n")
    before = guard.changed(repo)
    assert "notes.toml" in before
    assert guard.leaked(before, repo) == set(), "what was already there is nobody's leak"

    (repo / "both.png").write_bytes(b"\x89PNG")
    assert guard.leaked(before, repo) == {"both.png"}, "exactly the new path, and only it"


def test_the_guard_deletes_nothing(tmp_path):
    """A leak is REPORTED with its paths: whoever looks cleans up, not the harness."""
    guard = _guard()
    repo = _repo(tmp_path)
    denis = repo / "notes.toml"
    denis.write_text("# a line Denis is editing\n")
    before = guard.changed(repo)

    (repo / "junk.px6s").write_bytes(b"junk")
    assert guard.leaked(before, repo) == {"junk.px6s"}
    assert not hasattr(guard, "remove"), "the guard must have no way to delete anything"
    assert denis.is_file() and denis.read_text() == "# a line Denis is editing\n", \
        "another person's file is untouched"
    assert (repo / "junk.px6s").is_file(), "even the junk stays: the report names it"


def test_a_dirty_tree_at_the_start_is_normal(tmp_path):
    """A file somebody else left dirty is not a leak, and changing it again is not either."""
    guard = _guard()
    repo = _repo(tmp_path)
    (repo / "tracked.txt").write_text("changed by somebody else\n")
    before = guard.changed(repo)
    assert "tracked.txt" in before

    (repo / "tracked.txt").write_text("changed again, by the same person\n")
    assert guard.leaked(before, repo) == set(), "a file that was already dirty is not a leak"
