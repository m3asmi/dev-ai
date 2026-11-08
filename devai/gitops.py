"""Thin, bounded git helpers. Git is the only source of truth for the patch."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

GIT_TIMEOUT_S = 60
MAX_SCANNED_BYTES = 1_000_000


class GitError(RuntimeError):
    """A git command failed; the message carries git's own words."""


def git_bytes(cwd: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, timeout=GIT_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise GitError(f"git {' '.join(args)}: {error}") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).decode("utf-8", "replace").strip()
        raise GitError(f"git {' '.join(args)}: {detail}")
    return result.stdout


def git(cwd: Path, *args: str) -> str:
    return git_bytes(cwd, *args).decode("utf-8", "replace")


def main_root(cwd: Path) -> Path:
    """The main checkout, whether `cwd` is that checkout or one of its worktrees. After `git init
    --separate-git-dir` the common dir's parent is the metadata directory, not the checkout (codex,
    reviewing `init`; `git worktree list` gets it wrong too): from the checkout, `--show-toplevel`;
    from a worktree, the `core.worktree` the common dir records, else its parent."""
    common = Path(git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    if Path(git(cwd, "rev-parse", "--path-format=absolute", "--git-dir").strip()) == common:
        return Path(git(cwd, "rev-parse", "--show-toplevel").strip())
    recorded = git(common, "config", "--default", "", "core.worktree").strip()
    return (common / recorded).resolve() if recorded else common.parent


def current_branch(cwd: Path) -> str:
    return git(cwd, "rev-parse", "--abbrev-ref", "HEAD").strip()


def merge_base(worktree: Path, base_ref: str) -> str:
    """The commit the patch is judged against: where the task branch and its base part.
    After `git merge <base>` in the worktree it moves to the base's tip, so the base's
    own commits never count as the patch."""
    return git(worktree, "merge-base", base_ref, "HEAD").strip()


def tip(root: Path, ref: str) -> str:
    return git(root, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()


def untracked_files(worktree: Path) -> list[str]:
    listing = git(worktree, "ls-files", "--others", "--exclude-standard", "-z")
    return sorted(path for path in listing.split("\0") if path)


def ignored_files(worktree: Path) -> list[str]:
    """What git would delete or overwrite without a word: `worktree remove` and `merge` both
    treat an ignored file as expendable. dev-ai does not."""
    listing = git(worktree, "ls-files", "--others", "--ignored", "--exclude-standard", "-z")
    return sorted(path for path in listing.split("\0") if path)


def changed_files(worktree: Path, base_sha: str) -> list[str]:
    """Every path the patch touches: committed, staged, unstaged and untracked."""
    tracked = git(worktree, "diff", "--name-only", "--no-renames", "-z", base_sha, "--")
    paths = {path for path in tracked.split("\0") if path}
    return sorted(paths | set(untracked_files(worktree)))


def fingerprint(worktree: Path, base_sha: str) -> str:
    """Identity of the exact patch, by the content of every path it touches. Read from the worktree,
    not from `git diff`, whose output depends on whether a file is tracked: committing a new file used
    to change this hash without changing the patch, and threw away a passing check with its review
    (tasks 005 and 010, 2026-09-20). The mode is hashed too, as the diff's mode line was."""
    digest = hashlib.sha256()
    for path in changed_files(worktree, base_sha):
        file = worktree / path
        digest.update(b"\0" + path.encode("utf-8", "surrogateescape") + b"\0")
        try:
            if file.is_symlink():  # where it points, never what it points at, and by os.readlink, which
                digest.update(b"l" + os.readlink(file).encode("utf-8", "surrogateescape"))  # returns the text
                continue  # git stored: Path.readlink builds a Path, and `./twin.py` collapses to `twin.py`
            digest.update(b"x" if file.stat().st_mode & 0o100 else b"-")
            digest.update(hashlib.sha256(file.read_bytes()).digest())
        except OSError:  # nothing to read there: the patch deletes the path, or the host refuses it
            digest.update(b"absent")
    return digest.hexdigest()


def added_lines(worktree: Path, base_sha: str) -> list[str]:
    """Lines the patch adds. Impact is judged on these, never on whole files:
    a module that mentions `session` somewhere must not close the fast path for
    every later edit to it."""
    diff = git(worktree, "diff", "--no-renames", "-U0", base_sha, "--")
    lines = [
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]
    for text in untracked_text(worktree).values():
        lines.extend(text.splitlines())
    return lines


def untracked_text(worktree: Path) -> dict[str, str]:
    """The untracked files' text, each bounded: they are part of the patch too. A binary file, by git's rule (a NUL
    among its first 8 000 bytes), is named with its size as `git diff` names a tracked one (task 229)."""
    texts: dict[str, str] = {}
    for path in untracked_files(worktree):
        try:
            data = (worktree / path).read_bytes()
        except OSError:
            continue
        texts[path] = (f"(binary file, {len(data)} bytes)" if b"\0" in data[:8000]
                       else data[:MAX_SCANNED_BYTES].decode("utf-8", "replace"))
    return texts
