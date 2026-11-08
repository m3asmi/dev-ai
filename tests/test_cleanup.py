"""The two scripts that clean up after a merge delete what cannot be regenerated if they are
wrong, so both behaviours are proven: without `--yes` nothing goes, and with it only what the
arguments and the evidence allow. PostgreSQL is faked; git is a throwaway repository.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from conftest import sh

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def run(script: str, cwd: Path, *args: str, path: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PATH": path or os.environ["PATH"]}
    return subprocess.run(["bash", str(SCRIPTS / script), *args], cwd=cwd, env=env, capture_output=True, text=True)


def fake_postgres(tmp_path: Path) -> str:
    """`psql` answers two candidates and records its arguments and query; `dropdb` records."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "psql").write_text(
        f'#!/bin/sh\necho "$@" > {tmp_path}/psql.args\ncat > {tmp_path}/psql.sql\n'
        'printf "8 kB\\tci_a\\n1 MB\\tci b\\n"\n'
    )
    (bin_dir / "dropdb").write_text(f'#!/bin/sh\necho "$2" >> {tmp_path}/dropped\n')
    for name in ("psql", "dropdb"):
        (bin_dir / name).chmod(0o755)
    return f"{bin_dir}:{os.environ['PATH']}"


def test_drop_test_dbs_dry_run_drops_nothing_and_yes_drops_the_candidates(tmp_path: Path) -> None:
    path = fake_postgres(tmp_path)
    assert run("drop-test-dbs.sh", tmp_path, "--keep", "ci_prod", path=path).returncode == 2
    dry = run("drop-test-dbs.sh", tmp_path, "--match", "^ci_", "--keep", "ci_prod", "--keep", "a,b", path=path)
    assert dry.returncode == 0 and "ci b" in dry.stdout and not (tmp_path / "dropped").exists()
    args = (tmp_path / "psql.args").read_text()
    assert "match=^ci_" in args and "keep=ci_prod\na,b" in args
    assert "pg_stat_activity" in (tmp_path / "psql.sql").read_text()
    applied = run("drop-test-dbs.sh", tmp_path, "--match", "^ci_", "--yes", path=path)
    assert applied.returncode == 0 and (tmp_path / "dropped").read_text() == "ci_a\nci b\n"


def test_clean_worktrees_removes_only_those_whose_work_landed(repo: Path) -> None:
    wts = repo.parent / "wts"
    for name in ("landed", "orphan", "ahead", "deleted", "staged", "mode", "unignored", "opened"):
        sh(repo, "git", "worktree", "add", "-q", "-b", name, str(wts / name))
        (repo.parent / "tasks" / name).mkdir(parents=True)
        if name != "opened":
            (repo.parent / "tasks" / name / "landing.json").write_text("{}")
    # landed: its dirty file reached main in a commit since overwritten, its ignored cache is excused
    (wts / "landed" / "src" / "app.py").write_text("def answer():\n    return 42\n")
    (repo / ".git" / "info" / "exclude").write_text("cache.pyc\n")
    (wts / "landed" / "cache.pyc").write_text("bytes")
    (wts / "unignored" / "work.pyc").write_text("matches the glob, but git does not ignore it\n")  # codex, task 053
    (repo / "src" / "app.py").write_text("def answer():\n    return 42\n")
    sh(repo, "git", "commit", "-qam", "land")
    (repo / "src" / "app.py").write_text("def answer():\n    return 43\n")
    sh(repo, "git", "commit", "-qam", "move on")
    (wts / "orphan" / "notes.md").write_text("work that lives nowhere else\n")
    (wts / "ahead" / "new.py").write_text("x = 1\n")
    (wts / "deleted" / "src" / "legacy.py").unlink()
    (wts / "mode" / "src" / "legacy.py").chmod(0o755)
    (wts / "staged" / "new.py").write_text("y = 2\n")
    sh(wts / "staged", "git", "add", "new.py")
    sh(wts / "ahead", "git", "add", ".")
    sh(wts / "ahead", "git", "commit", "-qm", "unmerged")
    args = ("--base", "main", "--under", str(wts), "--tasks", str(repo.parent / "tasks"), "--ignore", "*.pyc")
    assert run("clean-worktrees.sh", repo, "--base", "main", "--under", str(wts)).returncode == 2
    dry = run("clean-worktrees.sh", repo, *args)
    assert dry.returncode == 0, dry.stderr
    assert "keeps orphan: notes.md never in main" in dry.stdout and "keeps ahead: HEAD not in main" in dry.stdout
    assert "keeps deleted: a deletion, rename or mode change" in dry.stdout
    assert "keeps staged: new.py never in main" in dry.stdout
    assert "keeps mode: a deletion, rename or mode change" in dry.stdout
    assert "keeps unignored: work.pyc never in main" in dry.stdout
    # opened: no commit, so its HEAD is in main; open tasks 347, 176, 177 went that way (2026-10-19)
    assert "keeps opened: its task has not landed" in dry.stdout
    assert all((wts / name).exists() for name in ("landed", "orphan", "ahead"))
    sh(repo, "git", "checkout", "-q", "--orphan", "other")  # codex, task 055: `branch -d` judged HEAD, not --base
    sh(repo, "git", "commit", "-q", "--allow-empty", "-m", "elsewhere")
    applied = run("clean-worktrees.sh", repo, *args, "--yes")
    assert applied.returncode == 0 and "removed landed" in applied.stdout, applied.stderr
    branches = sh(repo, "git", "branch", "--list")  # the bench, 2026-10-14: 17 merged branches left behind
    assert "landed" not in branches and "ahead" in branches
    assert not (wts / "landed").exists() and (wts / "orphan").exists() and (wts / "ahead").exists()
    assert (wts / "deleted").exists() and (wts / "opened").exists()
