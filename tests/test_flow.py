from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import set_test_command, sh
from test_cleanup import fake_postgres

from devai import cli, commands, gitops, testgate
from devai.task import TaskError, load, resolve


def open_task(repo: Path, slug: str = "fix-answer", paths: tuple[str, ...] = ("src/app.py",), **kw: str) -> Path:
    mandate = {"delivery": "merge", "author_model": "claude-opus-5", **kw}  # said here, as the operator says it
    return Path(commands.start(repo, slug, "make the answer right", list(paths), None, "claude", **mandate).worktree)


def fix_answer(worktree: Path) -> None:
    (worktree / "src" / "app.py").write_text("def answer():\n    return 42\n", encoding="utf-8")


def note(worktree: Path) -> None:
    """A patch of descriptive documentation only: the one kind that lands on its tests alone."""
    (worktree / "README.md").write_text("The answer is 42.\n", encoding="utf-8")


def dies(check: Callable[[], object]) -> bool:
    """True once `check` raises ProcessLookupError, within two seconds: init reaps an orphan shortly after its
    death, and macOS has no /proc to watch (review of the timeout fix)."""
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            check()
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def written_pid(path: Path) -> int:
    while not (path.is_file() and path.read_text(encoding="utf-8").strip().isdigit()):
        time.sleep(0.05)
    return int(path.read_text(encoding="utf-8"))


def interrupted(pgid: int) -> bool:
    raise KeyboardInterrupt  # the operator's Ctrl-C, landing in the grace period


# --- start ---------------------------------------------------------------

def test_start_opens_a_branch_and_a_worktree_under_the_state_dir(repo: Path) -> None:
    """Inside the checkout the harness already lets the agent write to: task 003 of this
    repository had to be moved there by hand from `../dev-ai.worktrees/`."""
    worktree = open_task(repo)
    assert worktree == (repo / ".dev-ai" / "worktrees" / "fix-answer").resolve() and worktree.is_dir()
    assert sh(worktree, "git", "rev-parse", "--abbrev-ref", "HEAD").strip() == "dev-ai/fix-answer"
    assert sh(repo, "git", "status", "--porcelain") == ""  # .dev-ai/ is excluded, no tracked file touched
    task = load(repo, "fix-answer")
    assert (task.delivery, task.author_model) == ("merge", "claude-opus-5")


def test_start_refuses_a_bad_name_an_unserved_or_nameless_author_and_a_duplicate(repo: Path) -> None:
    """The author's model: on 2026-09-20 (init-command, harness-commands) codex and opencode were
    unavailable and the fallback to the author's own harness was refused, the task having recorded
    no model to be other than; 12 of 35 tasks here lacked it. A human author has none to name."""
    with pytest.raises(TaskError, match="not a task name"):
        commands.start(repo, "Bad Name", "g", ["src"], None, "claude", author_model="m")
    with pytest.raises(TaskError, match="--author-model") as nameless:
        commands.start(repo, "ok", "g", ["src"], None, "codex")
    assert nameless.value.kind == "no_author_model" and not (repo / ".dev-ai/tasks/ok").exists()
    commands.start(repo, "by-hand", "g", ["src"], None, "human")
    with pytest.raises(SystemExit):  # argparse knows the authors there are
        cli.main(["start", "ok", "--goal", "g", "--paths", "src", "--author", "cursor", "--author-model", "m"], repo)
    assert not (repo / ".dev-ai/tasks/ok").exists()
    # the owner, 2026-10-27: opencode is a harness like claude and codex again, its model named
    assert cli.main(["start", "by-oc", "--goal", "g", "--paths", "src", "--author", "opencode", "--author-model",
                     "openai/gpt-6-sol"], repo) == 0 and load(repo, "by-oc").author == "opencode"
    open_task(repo)
    with pytest.raises(TaskError, match="already exists"):
        open_task(repo)
    recorded = repo / ".dev-ai/tasks/fix-answer/task.json"  # a task on record still loads, whoever wrote it
    recorded.write_text(recorded.read_text(encoding="utf-8").replace('"claude"', '"opencode"'), encoding="utf-8")
    assert load(repo, "fix-answer").author == "opencode" and commands.status(repo)[-1]["state"] == "open"


# --- check ---------------------------------------------------------------

def test_check_passes_an_in_scope_patch_with_green_tests(repo: Path) -> None:
    worktree = open_task(repo)
    fix_answer(worktree)
    result = commands.check(worktree, "fix-answer")
    assert result["verdict"] == "pass" and result["blockers"] == []
    assert result["changed_files"] == ["src/app.py"] and result["needs_review"] == ["src/app.py"]
    assert result["tests"]["exit_code"] == 0 and result["tests"]["command"] == "true"


def test_check_names_every_file_outside_the_scope_and_skips_the_tests(repo: Path) -> None:
    worktree = open_task(repo)
    fix_answer(worktree)
    (worktree / "src" / "extra.py").write_text("x = 1\n", encoding="utf-8")  # untracked counts too
    result = commands.check(worktree, "fix-answer")
    assert result["verdict"] == "fail" and result["tests"] is None
    assert "src/extra.py" in result["blockers"][0] and "scope-add" in result["blockers"][0]
    assert result["blocker_kinds"] == ["out_of_scope"]  # what the log counts: which check ever fired


def test_check_fails_on_red_tests_and_points_at_the_log(repo: Path) -> None:
    set_test_command(repo, "echo boom; exit 3")
    worktree = open_task(repo)
    fix_answer(worktree)
    result = commands.check(worktree, "fix-answer")
    assert result["verdict"] == "fail" and "exit 3" in result["blockers"][0]
    assert result["blocker_kinds"] == ["tests_failed"]
    assert "boom" in Path(result["tests"]["log"]).read_text(encoding="utf-8")


def test_check_refuses_an_empty_patch_and_a_missing_test_command(repo: Path) -> None:
    worktree = open_task(repo)
    empty = commands.check(worktree, "fix-answer")
    assert "patch is empty" in empty["blockers"][0] and empty["blocker_kinds"] == ["empty_patch"]
    (repo / "dev-ai.json").write_text("{}", encoding="utf-8")
    (repo / "dp-project.json").write_text(json.dumps({"test_command": "true"}), encoding="utf-8")  # never read
    fix_answer(worktree)
    untested = commands.check(worktree, "fix-answer")
    assert "no test command" in untested["blockers"][0] and untested["blocker_kinds"] == ["no_test_command"]


def test_tests_run_inside_the_worktree_of_the_patch(repo: Path) -> None:
    """The lesson of a three-hour loss: tests that load the main checkout prove nothing."""
    set_test_command(repo, 'test "$PWD" = "$DEV_AI_WORKTREE" && grep -q 42 src/app.py')
    worktree = open_task(repo)
    fix_answer(worktree)
    assert commands.check(worktree, "fix-answer")["verdict"] == "pass"


def test_a_patch_cannot_weaken_its_own_test_command(repo: Path) -> None:
    set_test_command(repo, "false")
    worktree = open_task(repo, paths=("src/app.py", "dev-ai.json"))
    fix_answer(worktree)
    (worktree / "dev-ai.json").write_text(json.dumps({"test_command": "true"}), encoding="utf-8")
    assert commands.check(worktree, "fix-answer")["verdict"] == "fail"  # the main checkout's command ran


def test_tests_that_outlast_their_timeout_are_not_tests_that_failed(repo: Path) -> None:
    """Without this the log reads `tests_failed` for a suite that hung, which is a different thing to
    go and fix, and `test_timeout` is a setting nothing reads (registered 2026-09-20). And the whole
    process group must end, not the shell alone: a probe of 2026-09-22 saw `sleep` outlive the check
    and the script's EXIT trap never run, which for Odoo is a server left on its test database. So a
    30 s sleep behind a one-second ceiling, and a trap writing its marker beside the worktree (inside
    it, the file would be `patch_moved`): the marker must be there, and the check must not have waited."""
    command = "bash -c \"trap 'touch ../cleaned' EXIT; sleep 30\""
    (repo / "dev-ai.json").write_text(json.dumps({"test_command": command, "test_timeout": 1}), encoding="utf-8")
    sh(repo, "git", "commit", "-qam", "a suite that hangs")
    worktree = open_task(repo)
    fix_answer(worktree)
    result = commands.check(worktree, "fix-answer")
    assert result["blocker_kinds"] == ["tests_timeout"] and result["tests"]["timed_out"] is True
    assert (worktree.parent / "cleaned").is_file() and result["tests"]["duration_s"] < 5


def test_the_timeout_ends_what_ignores_sigterm_and_bears_a_group_already_gone(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reviews of this fix (codex, 2026-09-22): SIGKILL followed the shell's exit, not the group's, so a
    descendant ignoring SIGTERM escaped; `killpg` on a group that had just finished raised instead of passing
    the Ctrl-C on; and a Ctrl-C during the grace skipped the SIGKILL. The sleep below ignores SIGTERM and
    writes its pid beside the worktree."""
    monkeypatch.setattr(testgate, "GRACE_S", 0.5)
    command = "bash -c \"trap '' TERM; echo \\$\\$ > ../pid; exec sleep 30\" & wait"
    (repo / "dev-ai.json").write_text(json.dumps({"test_command": command, "test_timeout": 1}), encoding="utf-8")
    sh(repo, "git", "commit", "-qam", "a suite that ignores SIGTERM")
    worktree = open_task(repo)
    fix_answer(worktree)
    result = commands.check(worktree, "fix-answer")
    assert result["blocker_kinds"] == ["tests_timeout"] and 1.5 <= result["tests"]["duration_s"] < 5
    pid = written_pid(worktree.parent / "pid")
    assert dies(lambda: os.kill(pid, 0))  # SIGKILL reached the sleep, not just its shell
    finished = subprocess.Popen("true", shell=True, start_new_session=True)
    finished.wait()
    testgate._end(finished)  # a group already gone is no error
    (worktree.parent / "pid").unlink()
    ignoring = subprocess.Popen(command, shell=True, cwd=worktree, start_new_session=True)
    pid = written_pid(worktree.parent / "pid")
    monkeypatch.setattr(testgate, "_present", interrupted)
    with pytest.raises(KeyboardInterrupt):
        testgate._end(ignoring)
    assert dies(lambda: os.kill(pid, 0))  # the SIGKILL still went out before the interrupt went up


def test_a_patch_that_moves_under_the_tests_is_not_a_tested_patch_and_stops_them(
        repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point 6c (2026-11-06): 264 of 345 checks that ended `patch_moved` had passing tests, run to their end after
    the move; in 92 % a review had ended meanwhile and its finding was being fixed. The check stops at the move, and
    what moved stays where it was written: a pre-commit fixer's fix, and the next check passes."""
    monkeypatch.setattr(testgate, "POLL_S", 0.2)
    set_test_command(repo, "echo generated > src/app.py && sleep 30")
    worktree = open_task(repo)
    fix_answer(worktree)
    result = commands.check(worktree, "fix-answer")
    assert "changed while the tests ran" in result["blockers"][0] and result["blocker_kinds"] == ["patch_moved"]
    assert result["tests"]["duration_s"] < 5 and (worktree / "src" / "app.py").read_text() == "generated\n"
    set_test_command(repo, "cp src/app.py ../k; trap 'cp ../k src/app.py' TERM; echo x > src/app.py; sleep 30 & wait")
    assert commands.check(worktree, "fix-answer")["blocker_kinds"] == ["patch_moved"]  # stopped, bytes put back (codex)


def test_committing_inside_the_worktree_is_not_a_change_to_the_patch(repo: Path) -> None:
    """The evidence binds to the patch's content, not to git's index. Committing a new file moved it
    out of `ls-files --others` and into `git diff`, and the old fingerprint hashed the two differently:
    a passing check and its review were thrown away for nothing on tasks 005 and 010, 2026-09-20."""
    worktree = open_task(repo, paths=("src/*",))
    fix_answer(worktree)
    (worktree / "src" / "extra.py").write_text("x = 1\n", encoding="utf-8")  # untracked, part of the patch
    checked = commands.check(worktree, "fix-answer")
    sh(worktree, "git", "add", "src/extra.py")
    staged = gitops.fingerprint(worktree, checked["base_sha"])
    sh(worktree, "git", "commit", "-qm", "the same patch, now committed")
    assert gitops.fingerprint(worktree, checked["base_sha"]) == checked["patch_sha256"] == staged
    (worktree / "src" / "extra.py").write_text("x = 2\n", encoding="utf-8")  # one byte, and it is another patch
    assert gitops.fingerprint(worktree, checked["base_sha"]) != checked["patch_sha256"]


def test_the_fingerprint_separates_patches_that_differ(repo: Path) -> None:
    """A guarantee the diff gave and content alone does not: an added path, a deletion, and the
    executable bit, which `git diff` carried as a mode line."""
    worktree = open_task(repo, paths=("src/*",))
    fix_answer(worktree)
    base = gitops.merge_base(worktree, "main")
    fixed = gitops.fingerprint(worktree, base)
    (worktree / "src" / "app.py").chmod(0o755)
    assert gitops.fingerprint(worktree, base) != fixed
    (worktree / "src" / "app.py").chmod(0o644)
    assert gitops.fingerprint(worktree, base) == fixed
    (worktree / "src" / "legacy.py").unlink()  # a path the patch deletes is read without raising
    deleted = gitops.fingerprint(worktree, base)
    assert deleted != fixed and "src/legacy.py" in gitops.changed_files(worktree, base)
    # A link is bound by where it points, never by what it points at: reading the target instead gave
    # a file and a link to a twin of it the same hash, so a check of the file stood for the link.
    (worktree / "src" / "twin.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
    both = gitops.fingerprint(worktree, base)
    (worktree / "src" / "app.py").unlink()
    (worktree / "src" / "app.py").symlink_to("twin.py")
    assert gitops.fingerprint(worktree, base) != both
    (worktree / "src" / "app.py").unlink()
    (worktree / "src" / "app.py").symlink_to("elsewhere.py")  # dangling: still the link it is, not a deletion
    dangling = gitops.fingerprint(worktree, base)
    assert dangling not in (both, deleted)
    (worktree / "src" / "app.py").unlink()  # codex, reviewing this: Path.readlink builds a Path, and a Path
    (worktree / "src" / "app.py").symlink_to("./elsewhere.py")  # collapses `./`; git stored the text it was given
    assert gitops.fingerprint(worktree, base) != dangling


def test_every_change_but_descriptive_documentation_needs_a_review(repo: Path) -> None:
    """The word list this replaces fired on `token` and not on `jeton`, and saw no guard removed:
    b2539df of this repository took a confirmation out and was classified neutral. Now the paths
    decide, whatever the lines say: only descriptive documentation lands on its tests alone."""
    worktree = open_task(repo, paths=("*",))
    for path in ("README.md", "docs/notes.rst", "AGENTS.md", "AGENTS.override.md", "docs/skill.md",
                 ".claude/settings.json", "src/droits_acces.py", "dev-ai.json", "requirements.txt"):
        (worktree / path).parent.mkdir(parents=True, exist_ok=True)
        (worktree / path).write_text("x\n", encoding="utf-8")
    checked = commands.check(worktree, "fix-answer")
    assert checked["needs_review"] == [".claude/settings.json", "AGENTS.md", "AGENTS.override.md", "dev-ai.json",
                                       "docs/skill.md", "requirements.txt", "src/droits_acces.py"]
    sh(worktree, "git", "checkout", "--", "dev-ai.json")
    for path in checked["changed_files"]:
        if path != "dev-ai.json":
            (worktree / path).unlink()
    (worktree / "src" / "legacy.py").write_text("", encoding="utf-8")  # a guard removed: deletions only
    assert commands.check(worktree, "fix-answer")["needs_review"] == ["src/legacy.py"]


# --- land ----------------------------------------------------------------

def test_land_commits_a_checked_documentation_patch_on_its_tests_alone(repo: Path) -> None:
    worktree = open_task(repo, paths=("README.md",))
    note(worktree)
    commands.check(worktree, "fix-answer")
    record = commands.land(worktree, "fix-answer", "docs: the answer", merge=False)
    assert record["merged"] is False and record["needs_review"] == [] and record["review"] == "not_run"
    assert record["reviewer"] == record["requested_model"] == ""  # nobody read it, and the record says so
    assert sh(worktree, "git", "log", "-1", "--format=%s").strip() == "docs: the answer"
    assert sh(worktree, "git", "status", "--porcelain") == ""


def test_land_refuses_an_unchecked_patch_and_a_patch_changed_since_its_check(repo: Path) -> None:
    worktree = open_task(repo)
    fix_answer(worktree)
    with pytest.raises(TaskError, match="no passing check"):
        commands.land(worktree, "fix-answer", "fix: x", merge=False)
    commands.check(worktree, "fix-answer")
    (worktree / "src" / "app.py").write_text("def answer():\n    return 43\n", encoding="utf-8")
    with pytest.raises(TaskError, match="changed since it was checked") as stale:
        commands.land(worktree, "fix-answer", "fix: x", merge=False)
    assert stale.value.kind == "unchecked"
    # A record the installed 0.5.0 wrote: `impact` and no `needs_review`. Read as documentation
    # only, it would have landed a behaviour-changing patch unread after the upgrade.
    checked_path = repo / ".dev-ai/tasks/fix-answer/check.json"
    checked = json.loads(checked_path.read_text(encoding="utf-8"))
    fix_answer(worktree)
    legacy_record = {key: value for key, value in checked.items() if key != "needs_review"} | {"impact": []}
    checked_path.write_text(json.dumps(legacy_record), encoding="utf-8")
    with pytest.raises(TaskError, match="predates this release") as legacy:
        commands.land(worktree, "fix-answer", "fix: x", merge=False)
    assert legacy.value.kind == "unchecked"


def test_land_merge_refuses_a_patch_whose_base_moved_until_it_is_checked_again_on_the_merged_tree(repo: Path) -> None:
    """What was tested is what lands: a patch checked on an older base never ran with main's later commits.
    A commit landing merges nothing, and waits for no base (the owner, 2026-09-29)."""
    worktree = open_task(repo, paths=("README.md",))
    note(worktree)
    commands.check(worktree, "fix-answer")
    (repo / "src" / "legacy.py").write_text("password = load_secret()\nlater = True\n", encoding="utf-8")
    sh(repo, "git", "commit", "-qam", "main moved on")
    with pytest.raises(TaskError, match="git merge main") as stale:
        commands.land(repo, "fix-answer", "docs: x", merge=True)
    assert stale.value.kind == "stale_base"
    assert commands.status(repo)[0]["next"] == "git merge main, then check"  # it read `land`, refused at once
    assert commands.land(worktree, "fix-answer", "docs: x", merge=False)["merged"] is False
    sh(worktree, "git", "merge", "-q", "--no-edit", "main")
    with pytest.raises(TaskError, match="base was merged") as unchecked:  # same hunk, another tree: not tested
        commands.land(repo, "fix-answer", None, merge=True)
    assert unchecked.value.kind == "unchecked"
    assert commands.check(worktree, "fix-answer")["changed_files"] == ["README.md"]  # main's commit is not the patch
    assert commands.land(repo, "fix-answer", None, merge=True)["merged"] is True
    assert "later = True" in (repo / "src" / "legacy.py").read_text(encoding="utf-8")


def ignored_files(worktree: Path) -> None:
    """One ignored file the operator put there, one cache a run leaves behind."""
    exclude = worktree.parent.parent.parent / ".git" / "info" / "exclude"  # shared by every worktree
    exclude.write_text(exclude.read_text(encoding="utf-8") + "*.local\n__pycache__/\n", encoding="utf-8")
    (worktree / "notes.local").write_text("kept out of git on purpose\n", encoding="utf-8")
    (worktree / "src" / "__pycache__").mkdir()
    (worktree / "src" / "__pycache__" / "app.pyc").write_bytes(b"\0")


def test_land_merge_merges_cleans_up_keeps_the_ignored_files_that_are_no_cache_and_never_pushes(repo: Path) -> None:
    worktree = open_task(repo, paths=("README.md",))
    note(worktree)
    ignored_files(worktree)
    commands.check(worktree, "fix-answer")
    record = commands.land(repo, "fix-answer", "docs: the answer", merge=True)
    assert record["merged"] is True and record["kept"] == ["notes.local"] and not worktree.exists()
    kept = repo / ".dev-ai" / "tasks" / "fix-answer" / "kept"
    assert (kept / "notes.local").read_text(encoding="utf-8") == "kept out of git on purpose\n"
    assert not (kept / "src").exists()  # the cache went with the worktree
    assert "42" in (repo / "README.md").read_text(encoding="utf-8")
    assert "dev-ai/fix-answer" not in sh(repo, "git", "branch", "--list")
    assert sh(repo, "git", "remote") == ""
    for again in (lambda: commands.land(repo, "fix-answer", None, merge=False),
                  lambda: commands.check(repo, "fix-answer")):
        with pytest.raises(TaskError, match="nothing is left") as done:  # task 034, merged, asked again: git's error
            again()
        assert done.value.kind == "worktree_gone"


def test_a_cleanup_that_fails_after_the_merge_leaves_a_task_recorded_as_merged(
    repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The merge is the delivery. `landing.json` was written after the worktree and the branch were
    removed, so a failure there left a merged patch that `status` called open (an audit of 0.9.1)."""
    worktree = open_task(repo, paths=("README.md",))
    note(worktree)
    commands.check(worktree, "fix-answer")
    real = gitops.git

    def git(cwd: Path, *args: str) -> str:
        if args[:2] == ("branch", "-d"):
            raise gitops.GitError("git branch -d: a transient failure")
        return real(cwd, *args)

    monkeypatch.setattr(gitops, "git", git)
    with pytest.raises(gitops.GitError):
        commands.land(repo, "fix-answer", "docs: the answer", merge=True)
    assert "42" in (repo / "README.md").read_text(encoding="utf-8")
    assert commands.status(repo)[0]["state"] == "merged"


def test_land_merge_is_within_the_mandate_recorded_at_start_or_not_at_all(repo: Path) -> None:
    """The mandate `start` records is what `land` may do. A task from before mandates existed
    never agreed to a merge, so it loads as `commit`: nothing is gained by upgrading the tool."""
    started = commands.start(repo, "fix-answer", "make the answer right", ["README.md"], None, "claude",
                             author_model="claude-opus-5")
    worktree = Path(started.worktree)  # no mandate said, by the CLI or by a caller: `commit` (opencode, reviewing this)
    note(worktree)
    commands.check(worktree, "fix-answer")
    with pytest.raises(TaskError, match="mandate .* is to commit") as refused:
        commands.land(repo, "fix-answer", "docs: x", merge=True)
    assert refused.value.kind == "no_mandate" and sh(worktree, "git", "status", "--porcelain") != ""
    (repo / "src" / "legacy.py").write_text("password = load_secret()\nlater = True\n", encoding="utf-8")
    sh(repo, "git", "commit", "-qam", "main moved on")  # a commit landing merges nothing: the base is not its business
    assert commands.status(repo)[0]["next"] == "land"
    assert commands.land(worktree, "fix-answer", "docs: x", merge=False)["merged"] is False
    record = json.loads((repo / ".dev-ai/tasks/fix-answer/task.json").read_text(encoding="utf-8"))
    for legacy in ("delivery", "author_model"):
        del record[legacy]
    record["profile"] = "deep"  # written until 0.15.0 and read by nothing since: the record still loads
    (repo / ".dev-ai/tasks/fix-answer/task.json").write_text(json.dumps(record), encoding="utf-8")
    assert load(repo, "fix-answer").delivery == "commit" and commands.status(repo)[0]["check"] == "pass"


def test_land_merge_checks_the_main_checkout_before_committing_anything(repo: Path) -> None:
    """git's own rule. The bench's main checkout is never clean, and refusing any dirt there
    sent both of its first tasks to a hand merge: only what the merge would collide with blocks."""
    worktree = open_task(repo, paths=("README.md",))
    note(worktree)
    commands.check(worktree, "fix-answer")
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")  # a file of the patch, untracked here
    (repo / "notes.txt").write_text("unrelated\n", encoding="utf-8")
    with pytest.raises(TaskError, match="README.md") as refused:
        commands.land(worktree, "fix-answer", "docs: x", merge=True)
    assert refused.value.kind == "dirty_checkout"
    assert sh(worktree, "git", "status", "--porcelain") != ""  # nothing was committed
    (repo / "README.md").unlink()
    sh(repo, "git", "add", "notes.txt")
    with pytest.raises(TaskError, match="staged"):
        commands.land(repo, "fix-answer", "docs: x", merge=True)
    sh(repo, "git", "reset", "-q", "notes.txt")
    (repo / "src" / "legacy.py").write_text("password = load_secret()\nwip = 1\n", encoding="utf-8")
    assert commands.land(repo, "fix-answer", "docs: x", merge=True)["merged"] is True
    assert (repo / "notes.txt").is_file() and "wip" in (repo / "src" / "legacy.py").read_text(encoding="utf-8")


def test_land_merge_refuses_where_the_patch_would_overwrite_an_ignored_file_or_directory(repo: Path) -> None:
    """git refuses to overwrite an untracked file and silently overwrites an ignored one: a `.env` left in the main
    checkout is exactly the file a patch must never replace unasked. Codex, reviewing this patch, showed the same loss
    for an ignored file where the patch puts a directory, and an ignored directory where it puts a file."""
    (repo / ".git" / "info" / "exclude").write_text("docs/local.md\nnotes.md\nbuild\n", encoding="utf-8")  # shared
    worktree = open_task(repo, paths=("docs", "notes.md", "build"))
    for path in ("docs/local.md", "notes.md", "build/out.md"):
        (worktree / path).parent.mkdir(exist_ok=True)
        (worktree / path).write_text("from the patch\n", encoding="utf-8")
        sh(worktree, "git", "add", "-f", path)
    commands.check(worktree, "fix-answer")
    (repo / "docs").mkdir()
    (repo / "docs" / "local.md").write_text("someone else's, ignored\n", encoding="utf-8")  # the same path
    (repo / "notes.md").mkdir()
    (repo / "notes.md" / "private.txt").write_text("a directory where the patch puts a file\n", encoding="utf-8")
    (repo / "build").write_text("a file where the patch puts a directory\n", encoding="utf-8")
    with pytest.raises(TaskError, match="build/out.md, docs/local.md, notes.md") as refused:
        commands.land(worktree, "fix-answer", "docs: x", merge=True)
    assert refused.value.kind == "dirty_checkout"
    assert "someone else" in (repo / "docs" / "local.md").read_text(encoding="utf-8")  # all three untouched
    assert (repo / "notes.md" / "private.txt").is_file() and (repo / "build").is_file()


def test_the_three_landing_guards_no_task_had_yet_met_fire_and_name_themselves(repo: Path) -> None:
    """`wrong_branch` is the one that matters: without it `--merge` merges the task branch into
    whatever branch the main checkout happens to be sitting on. All three were registered kinds the
    budget test proved used, and the log of both repositories showed none of them had ever fired."""
    worktree = open_task(repo, paths=("README.md",))
    note(worktree)
    commands.check(worktree, "fix-answer")
    with pytest.raises(TaskError, match="no message") as unsaid:
        commands.land(worktree, "fix-answer", None, merge=False)
    assert unsaid.value.kind == "no_message"
    sh(repo, "git", "checkout", "-qb", "elsewhere")
    with pytest.raises(TaskError, match="needs the main checkout on 'main'") as astray:
        commands.land(worktree, "fix-answer", "docs: the answer", merge=True)
    assert astray.value.kind == "wrong_branch"
    sh(worktree, "git", "checkout", "-q", "--detach")  # the worktree is there, off its branch: said as such
    with pytest.raises(TaskError, match="not on dev-ai/fix-answer") as off:
        commands.check(repo, "fix-answer")
    assert off.value.kind == "wrong_branch" and "git branch dev-ai/fix-answer" in str(off.value)
    shutil.rmtree(worktree)  # by hand, so that git still lists it: what it lists is not what stands there
    with pytest.raises(TaskError, match="is gone") as vanished:  # asked from the main checkout: the other is gone
        commands.check(repo, "fix-answer")
    assert vanished.value.kind == "worktree_gone"
    for stand_in in (worktree.mkdir, lambda: sh(repo, "git", "clone", "-q", str(repo), str(worktree))):
        stand_in()  # a plain directory, then another repository, where git's worktree stood (codex, on task 040)
        with pytest.raises(TaskError, match="is gone") as unlanded:
            commands.land(repo, "fix-answer", "docs: the answer", merge=False)
        assert unlanded.value.kind == "worktree_gone"
    for way in ("move it away", "nothing is left", "git worktree prune", "git worktree add", "git reflog",
                "dev-ai drop fix-answer", "--destroy"):  # codex, on task 040: drop first would empty a stand-in
        assert way in str(unlanded.value), "the blocker tells no state apart: it says what to do in each"


# --- drop ----------------------------------------------------------------

def test_drop_destroys_work_that_lives_nowhere_else_only_when_told_to(repo: Path) -> None:
    """dev-pipeline never cleaned up: stale worktrees piled up and blocked re-runs. Here `drop`
    cleans up, and refuses while uncommitted or unmerged work would be lost."""
    worktree = open_task(repo)
    fix_answer(worktree)
    with pytest.raises(TaskError, match="1 uncommitted") as refused:
        commands.drop(repo, "fix-answer")
    assert refused.value.kind == "lost_work" and worktree.is_dir()  # nothing was destroyed
    sh(worktree, "git", "commit", "-qam", "fix: the answer")
    with pytest.raises(TaskError, match="on no other branch"):
        commands.drop(repo, "fix-answer")  # committed on its branch, merged nowhere
    record = commands.drop(repo, "fix-answer", destroy=True)
    assert record["lost_work"] is True and not worktree.exists()
    assert "dev-ai/fix-answer" not in sh(repo, "git", "branch", "--list")
    assert (repo / ".dev-ai/tasks/fix-answer/task.json").is_file()  # the record stays
    assert commands.status(repo)[0]["state"] == "dropped"


def test_drop_with_nothing_to_lose_asks_nothing_keeps_the_ignored_files_that_are_no_cache_and_runs_again(
    repo: Path) -> None:
    """`git worktree remove` deletes an ignored file without a word, and a `.env` copied in to run
    the suite is not regenerable; a cache is in every checked worktree, so refusing would fire every
    time. The file is kept under the task's record, the cache goes, nobody is asked."""
    worktree = open_task(repo)
    ignored_files(worktree)
    record = commands.drop(repo, "fix-answer")
    assert record["lost_work"] is False and record["kept"] == ["notes.local"] and not worktree.exists()
    kept = repo / ".dev-ai" / "tasks" / "fix-answer" / "kept"
    assert (kept / "notes.local").is_file() and not (kept / "src").exists()
    commands.drop(repo, "fix-answer")  # again, after the fact: still fine
    docs_worktree = open_task(repo, slug="merged-one", paths=("README.md",))
    note(docs_worktree)
    commands.check(docs_worktree, "merged-one")
    commands.land(repo, "merged-one", "docs: the answer", merge=True)
    commands.drop(repo, "merged-one")  # already merged and cleaned by land: nothing left to destroy
    assert [row["state"] for row in commands.status(repo)] == ["dropped", "merged"]
    # What the repository declared at init goes too, beside the caches (a Next.js site, 10-14: `.next/` everywhere)
    (repo / "dev-ai.json").write_text('{"test_command": "true", "disposable": ["*/.next/*"]}', encoding="utf-8")
    site = open_task(repo, slug="site", paths=("README.md",))
    ignored_files(site)
    exclude = repo / ".git" / "info" / "exclude"
    exclude.write_text(exclude.read_text(encoding="utf-8") + ".next/\n", encoding="utf-8")
    (site / "web" / ".next").mkdir(parents=True)
    (site / "web" / ".next" / "BUILD_ID").write_text("x\n", encoding="utf-8")
    assert commands.drop(repo, "site")["kept"] == ["notes.local"]


def test_drop_of_a_stacked_task_whose_base_branch_is_gone(repo: Path) -> None:
    """The bench, 2026-10-14: `branch --merged` on a deleted base raised, and nothing could be dropped."""
    open_task(repo, slug="base-one")
    stacked = Path(commands.start(repo, "stacked", "g", ["src/app.py"], "dev-ai/base-one", "claude",
                                  author_model="claude-opus-5").worktree)
    fix_answer(stacked)
    sh(stacked, "git", "commit", "-qam", "fix: the answer")
    commands.drop(repo, "base-one", destroy=True)
    with pytest.raises(TaskError, match="on no other branch") as refused:
        commands.drop(repo, "stacked")  # its work lives nowhere else now
    assert refused.value.kind == "lost_work" and stacked.is_dir()
    assert commands.drop(repo, "stacked", destroy=True)["lost_work"] is True and not stacked.exists()
    (repo / ".dev-ai" / "tasks" / ".claude").mkdir()  # Claude Code writes there: no task
    assert [row["task"] for row in commands.status(repo)] == ["base-one", "stacked"]


# --- scope, status, log --------------------------------------------------

def test_widening_a_scope_needs_a_reason_and_is_recorded(repo: Path) -> None:
    worktree = open_task(repo)
    with pytest.raises(TaskError, match="reason") as refused:
        commands.scope_add(repo, "fix-answer", ["src/extra.py"], "")
    assert refused.value.kind == "no_scope"
    task = commands.scope_add(repo, "fix-answer", ["src/extra.py"], "discovered while fixing")
    assert task.scope_paths == ["src/app.py", "src/extra.py"]
    assert task.scope_history[0]["reason"] == "discovered while fixing"
    (worktree / "src" / "extra.py").write_text("x = 1\n", encoding="utf-8")
    assert commands.check(worktree, "fix-answer")["blocker_kinds"] == []


def test_status_confronts_the_evidence_with_the_repository_and_names_the_next_step(repo: Path) -> None:
    """On this repository `status` showed a check's old pass beside an edited worktree."""
    worktree = open_task(repo)
    assert commands.status(repo)[0]["next"] == "check"
    fix_answer(worktree)
    commands.check(worktree, "fix-answer")
    row = commands.status(repo)[0]
    assert (row["check"], row["review"], row["next"]) == ("pass", "-", "review")
    (worktree / "src" / "app.py").write_text("def answer():\n    return 43\n", encoding="utf-8")
    row = commands.status(repo)[0]
    assert (row["check"], row["next"]) == ("stale", "check")
    commands.check(worktree, "fix-answer")
    set_test_command(repo, "true && true")  # another contract: the pass under the old one is no evidence
    assert commands.status(repo)[0]["check"] == "stale"


def test_status_reads_a_commit_merged_by_hand_as_merged_with_its_verdicts(repo: Path) -> None:
    """2026-10-15: tasks 414 and 416, merged by hand as `land` prescribes, read stale forever."""
    worktree = open_task(repo, paths=("README.md",), delivery="commit")
    note(worktree)
    commands.check(worktree, "fix-answer")
    commands.land(repo, "fix-answer", "docs: the answer", merge=False)
    stacked = Path(commands.start(repo, "stacked", "g", ["docs/x.md"], "dev-ai/fix-answer", "claude",
                                  author_model="claude-opus-5").worktree)  # its 418, on 416's branch
    (stacked / "docs").mkdir()
    (stacked / "docs" / "x.md").write_text("x\n", encoding="utf-8")
    commands.check(stacked, "stacked")
    commands.land(repo, "stacked", "docs: x", merge=False)
    assert [row["state"] for row in commands.status(repo)] == ["committed", "committed"]
    sh(repo, "git", "merge", "-q", "--no-ff", "-m", "merge by hand", "dev-ai/stacked")  # 416 and 418 at once
    assert [(row["state"], row["check"], row["next"]) for row in commands.status(repo)] == [("merged", "pass", "-")] * 2
    sh(repo, "git", "update-ref", "-d", "refs/heads/dev-ai/fix-answer")  # codex, task 057: `clean` deletes it now
    assert commands.status(repo)[1]["state"] == "merged"


def test_cli_finds_the_task_from_the_worktree_and_logs_every_command(
    repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo.parent / "spec.md").write_text("INV-1: the answer is 42\n", encoding="utf-8")
    start = ["start", "fix-answer", "--goal", "g", "--paths", "README.md", "--spec", "../spec.md",
             "--author-model", "claude-fable-5-1"]
    assert cli.main(start, cwd=repo) == 0
    assert "INV-1" in (repo / ".dev-ai/tasks/fix-answer/spec.md").read_text(encoding="utf-8")
    task = json.loads((repo / ".dev-ai/tasks/fix-answer/task.json").read_text())
    # No --delivery typed: `commit`. A merge is the operator's word (2026-09-21), never the default of a flag left out.
    assert (task["delivery"], task["author_model"]) == ("commit", "claude-fable-5-1") and "profile" not in task
    worktree = Path(task["worktree"])
    assert cli.main(["check"], cwd=worktree) == 1  # empty patch: blocked, with a reason
    note(worktree)
    assert cli.main(["check"], cwd=worktree) == 0
    assert cli.main(["land", "-m", "docs: the answer", "-m", "Body kept."], cwd=worktree) == 0  # logistics 462: as git
    assert sh(repo, "git", "log", "-1", "--format=%B", "dev-ai/fix-answer").rstrip() == "docs: the answer\n\nBody kept."
    assert cli.main(["check"], cwd=repo) == 1  # main checkout is no task
    assert cli.main(["status"], cwd=repo) == 0
    printed = capsys.readouterr().out
    assert "fix-answer" in printed and "dev-ai clean --yes" in printed  # a command, not names to drop (2026-09-27)
    rows = [json.loads(line) for line in (repo / ".dev-ai/log.jsonl").read_text().splitlines()]
    assert [(row["command"], row["outcome"]) for row in rows] == [
        ("start", "ok"), ("check", "blocked"), ("check", "ok"), ("land", "ok"), ("check", "blocked"), ("status", "ok"),
    ]
    assert all(row["at"].endswith("Z") and row["duration_ms"] >= 0 and row["version"] for row in rows)
    assert rows[0]["delivery"] == "commit" and rows[1]["blockers"] == ["empty_patch"]
    assert rows[4]["kind"] == "not_a_task"


def test_clean_lists_then_removes_landed_worktrees_and_the_databases_dev_ai_json_names(
    repo: Path, capfd: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    landed, open_work = open_task(repo, "fix-answer", ("README.md",)), open_task(repo, "open-work")
    note(landed)
    commands.check(landed, "fix-answer")
    commands.land(landed, "fix-answer", "docs: the answer", False)
    sh(repo, "git", "merge", "-q", "--no-edit", "dev-ai/fix-answer")
    fix_answer(open_work)  # work that lives nowhere else: its worktree stays
    (landed / "web" / ".next").mkdir(parents=True)  # ignored and declared disposable: no reason to keep
    (landed / "web" / ".next" / "BUILD_ID").write_text("x\n", encoding="utf-8")
    exclude = repo / ".git" / "info" / "exclude"
    exclude.write_text(exclude.read_text(encoding="utf-8") + ".next/\n", encoding="utf-8")
    (repo / "dev-ai.json").write_text('{"test_command": "true", "disposable": ["*/.next/*"]}', encoding="utf-8")
    monkeypatch.setenv("PATH", fake_postgres(repo.parent))
    assert commands.clean(repo, False) == 0 and landed.exists()  # a dry run lists
    out = capfd.readouterr().out
    assert "landed fix-answer" in out and "keeps open-work" in out and "test_databases" in out
    assert not (repo.parent / "psql.args").exists()  # none named: no database is even looked at
    declared = {"test_command": "true", "test_databases": "^ci_", "disposable": ["*/.next/*"]}
    (repo / "dev-ai.json").write_text(json.dumps(declared), encoding="utf-8")
    assert commands.clean(open_work, False) == 0 and landed.exists() and not (repo.parent / "dropped").exists()
    assert "match=^ci_" in (repo.parent / "psql.args").read_text() and "ci b" in capfd.readouterr().out
    assert commands.clean(open_work, True) == 0  # from any checkout of the repository
    assert not landed.exists() and open_work.exists() and (repo.parent / "dropped").read_text() == "ci_a\nci b\n"


def test_a_task_answers_to_its_number_written_any_way(repo: Path) -> None:
    """`--task 7`, not a slug the operator has to remember exactly."""
    open_task(repo)
    open_task(repo, "other-task", ("src/legacy.py",))

    assert [resolve(repo, wanted) for wanted in ("1", "001", "task-001", "TASK-1", "fix-answer")] == ["fix-answer"] * 5
    assert resolve(repo, "2") == "other-task"
    with pytest.raises(TaskError, match="no task '404'"):
        resolve(repo, "404")
    with pytest.raises(TaskError, match="no task"):
        resolve(repo, "../../../etc")  # a name is never joined into a path unchecked
    assert cli.main(["drop", "2"], cwd=repo) == 0 and commands.status(repo)[1]["state"] == "dropped"
    open_task(repo, "2", ("README.md",))  # a task literally named 2, beside the one numbered 2
    with pytest.raises(TaskError, match="names 2 tasks") as both:
        resolve(repo, "2")
    assert both.value.kind == "ambiguous_task"  # said, never guessed: resolve is the one gate to a task path


# --- init ----------------------------------------------------------------

def test_init_prepares_a_repository_once_and_keeps_what_is_there(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The bench was migrated by hand on 2026-09-20: dev-ai.json written, the note pasted three times
    before it was single-sourced, `.dev-ai/` excluded by the first start. One command, idempotent."""
    root = tmp_path / "plain"
    root.mkdir()
    sh(root, "git", "init", "-q", "-b", "main")
    (root / "AGENTS.md").write_text("# AGENTS.md\n\nHouse rules.\n", encoding="utf-8")
    assert cli.main(["init"], cwd=root) == 1 and "--test-command" in capsys.readouterr().err
    assert cli.main(["init", "--test-command", "true"], cwd=root) == 0
    assert json.loads((root / "dev-ai.json").read_text(encoding="utf-8")) == {"test_command": "true"}
    agents = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith("# AGENTS.md\n\nHouse rules.\n\n## Working with dev-ai\n\n- Open the task")
    assert agents.endswith(commands._note()) and "This repository is migrated" not in agents
    assert ".dev-ai/" in (root / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    before = {name: (root / name).read_text(encoding="utf-8") for name in ("dev-ai.json", "AGENTS.md")}
    assert cli.main(["init", "--test-command", "false"], cwd=root) == 0  # a second run changes nothing
    assert {name: (root / name).read_text(encoding="utf-8") for name in before} == before
    printed = capsys.readouterr().out
    assert printed.count("kept") == 4 and "kept, running `true`" in printed  # not the `false` just typed; 1 rule file
    assert "none granted" not in printed  # 0.10.0 still printed it, under a report saying rules were written
    (root / "dev-ai.json").write_text('{"review_timeout": 60}', encoding="utf-8")
    assert commands.init(root, "true")["dev-ai.json"] == "kept, but it declares no test_command"
    # The globs come from the agent that runs init, which reads the repository; dev-ai only records them
    assert commands.init(root, "true", ["*/.next/*"])["disposable"] == "added (1)"
    assert json.loads((root / "dev-ai.json").read_text()) == {"review_timeout": 60, "disposable": ["*/.next/*"]}
    assert commands.init(root, "true", ["*/dist/*"])["disposable"] == "kept (1)"  # the repository's own, maybe edited
    (root / "dev-ai.json").write_text('{"test_command": "true", "disposable": []}', encoding="utf-8")  # declares none
    assert commands.init(root, "true", ["*/dist/*"])["disposable"] == "added (1)"
    (root / "dev-ai.json").write_text('{"test_command": "true",}', encoding="utf-8")  # unread: never rewritten (codex)
    assert commands.init(root, "true", ["*/dist/*"])["disposable"].startswith("none declared")
    assert (root / "dev-ai.json").read_text(encoding="utf-8") == '{"test_command": "true",}'
    bare = tmp_path / "bare"
    bare.mkdir()
    sh(bare, "git", "init", "-q", "-b", "main")
    assert cli.main(["init", "--test-command", "true"], cwd=bare) == 0
    assert (bare / "AGENTS.md").read_text(encoding="utf-8").startswith("# AGENTS.md\n\n## Working with dev-ai\n")
    assert "none declared" in capsys.readouterr().out
    assert cli.main(["init", "--disposable", "*/.next/*", "--disposable", "*.tsbuildinfo"], cwd=bare) == 0
    assert json.loads((bare / "dev-ai.json").read_text())["disposable"] == ["*/.next/*", "*.tsbuildinfo"]


def test_init_never_writes_through_a_symlink_and_a_mention_is_not_the_heading(tmp_path: Path) -> None:
    """Codex, reviewing this command: an `AGENTS.md` linked to a shared file outside the checkout would
    have received the note, as the operator's own `~/.claude/CLAUDE.md` links into a vault; and a
    sentence quoting the heading read as the section itself."""
    linked = tmp_path / "linked"
    linked.mkdir()
    sh(linked, "git", "init", "-q", "-b", "main")
    shared = tmp_path / "shared-instructions.md"
    shared.write_text("Setup adds `## Working with dev-ai` here.\n", encoding="utf-8")
    (linked / "AGENTS.md").symlink_to(shared)
    with pytest.raises(TaskError, match="symlink"):
        commands.init(linked, "true")
    assert shared.read_text(encoding="utf-8").count("\n") == 1 and not (linked / "dev-ai.json").exists()
    (linked / "dev-ai.json").symlink_to(tmp_path / "nowhere.json")  # dangling: is_file() says no, a write follows
    with pytest.raises(TaskError, match="dev-ai.json, AGENTS.md"):
        commands.init(linked, "true")
    assert not (tmp_path / "nowhere.json").exists()
    for name in ("dev-ai.json", "AGENTS.md"):
        (linked / name).unlink()
    (linked / "AGENTS.md").write_text(shared.read_text(encoding="utf-8"), encoding="utf-8")
    assert commands.init(linked, "true")["AGENTS.md"] == "note appended"
    assert "\n## Working with dev-ai\n\n- Open the task" in (linked / "AGENTS.md").read_text(encoding="utf-8")
    exclude = linked / ".git" / "info" / "exclude"
    exclude.write_text("# .dev-ai/\n", encoding="utf-8")  # a comment is not a rule
    assert commands.init(linked, "true")[".dev-ai/"] == "excluded from git status"
    sh(linked, "git", "check-ignore", "-q", ".dev-ai/")  # exit 1, so an error, when not excluded
    exclude.unlink()
    exclude.symlink_to(shared)
    assert commands.init(linked, "true")[".dev-ai/"].startswith("left alone")
    assert shared.read_text(encoding="utf-8").count("\n") == 1  # never written through


def test_init_writes_the_rules_of_this_repository_so_the_flow_runs_unprompted(tmp_path: Path) -> None:
    """The owner, 2026-09-21: the flow runs unprompted, except what destroys; the rules never name `drop`.
    2026-10-02: codex asked at every command: a codex rule of the repository. 2026-10-27: opencode is served
    again and gets no rule: its last matching rule wins, so ours would undo his deny (codex, task 059).
    2026-11-04: Claude Code's trust prompt warned on every migrated repository about the rules init wrote
    under `.claude/`; the owner moved them to his user settings, and init writes none for Claude."""
    root, local, rules = tmp_path / "plain", ".claude/settings.local.json", ".codex/rules/dev-ai.rules"
    root.mkdir()
    sh(root, "git", "init", "-q", "-b", "main")
    his = json.dumps({"permission": {"bash": {"*": "ask"}}})
    (root / "opencode.json").write_text(his, encoding="utf-8")
    report = commands.init(root, "true")
    assert not (root / ".claude").exists() and local not in report
    assert ('prefix_rule(pattern = ["dev-ai", ["status", "start", "check", "scope-add", "review", "land"]], '
            'decision = "allow")') in (root / rules).read_text(encoding="utf-8")
    assert (root / "opencode.json").read_text(encoding="utf-8") == his and list(report)[-1] == rules
    assert not (root / ".opencode").exists()
    assert "written" in report[rules] and "granted" not in " ".join(report.values())
    sh(root, "git", "check-ignore", "-q", rules)  # created here, so excluded; exit 1, an error, otherwise
    before = (root / rules).read_text(encoding="utf-8")
    assert commands.init(root, "true")[rules] == "kept"  # a second run changes nothing
    assert (root / rules).read_text(encoding="utf-8") == before
    (root / local).parent.mkdir()
    (root / local).write_text("{ his own", encoding="utf-8")  # an earlier release's file, or his: never touched
    commands.init(root, "true")
    assert (root / local).read_text(encoding="utf-8") == "{ his own"
    shutil.rmtree(root / ".codex")  # linked to the operator's own, the repository's rule would be a user-wide one
    (user := tmp_path / "user-codex").mkdir()
    (root / ".codex").symlink_to(user)
    assert "left as it is" in commands.init(root, "true")[rules] and not any(user.iterdir())


def test_main_root_is_the_checkout_under_a_separate_git_dir_too(tmp_path: Path) -> None:
    """Codex, reviewing `init`: after `git init --separate-git-dir`, the parent of `--git-common-dir`
    is the metadata directory, and every command would have written its state and files there."""
    checkout, metadata = tmp_path / "checkout", tmp_path / "metadata.git"
    checkout.mkdir()
    sh(checkout, "git", "init", "-q", "-b", "main", f"--separate-git-dir={metadata}")
    assert gitops.main_root(checkout).resolve() == checkout.resolve()
    assert commands.init(checkout, "true")["dev-ai.json"] == "written" and (checkout / "dev-ai.json").is_file()
    assert ".dev-ai/" in (metadata / "info" / "exclude").read_text(encoding="utf-8")
