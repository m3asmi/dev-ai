"""The verbs that need no model: start, check, land, drop, scope-add, status, clean.

No model runs here. Development happens in the worktree with whatever harness
and model the operator chose; these commands contain the work and prove it. What
each may do is what the harness's own permission prompt lets it do, in the
repository where it runs: dev-ai asks for no terminal of its own.
"""

from __future__ import annotations

import json
import shutil
import statistics
import subprocess
from datetime import datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from . import gitops, review, testgate
from .task import (
    MAX_SPEC_LINES,
    Task,
    TaskError,
    checked_now,
    config,
    disposable,
    from_record,
    load,
    next_number,
    now,
    patch_of,
    read_json,
    save,
    state_dir,
    task_dir,
    test_command,
    valid_slug,
    worktree_of,
)

Blockers = list[tuple[str, str]]  # (kind, message): the log counts kinds, the operator reads messages


def _exclude(root: Path, entry: str = ".dev-ai/") -> str:
    """Keep `entry` out of `git status` without touching a tracked file: `excluded`, `kept`, or left
    alone when the exclude file is a symlink, since a write would follow it (codex, reviewing `init`)."""
    common = gitops.git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    exclude = Path(common) / "info" / "exclude"  # not `--git-path`: its absolute form resolves the link itself
    existing = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    if any(line.strip() == entry for line in existing.splitlines()):  # a comment is not a rule
        return "kept"
    if exclude.is_symlink():
        return f"left alone: {exclude} is a symlink; exclude {entry} yourself"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text(existing.rstrip("\n") + f"\n{entry}\n", encoding="utf-8")
    return "excluded from git status"


NOTE_HEADING = "## Working with dev-ai"


def _has_note(text: str) -> bool:
    """The heading as a line of its own: a sentence quoting it is not the section (codex, reviewing this)."""
    return any(line.rstrip() == NOTE_HEADING for line in text.splitlines())


def _note() -> str:
    """The bullets of this tool's own AGENTS.md note, the one copy there is: on 2026-09-20 the same
    text was pasted into the bench by hand, three times, before it was single-sourced."""
    text = (Path(__file__).resolve().parents[1] / "AGENTS.md").read_text(encoding="utf-8")
    section = text.split("\n" + NOTE_HEADING + "\n", 1)[1].split("\n## ", 1)[0]
    return "\n".join(line for line in section.splitlines() if line.startswith(("- ", "  "))) + "\n"


VERBS = ("status", "start", "check", "scope-add", "review", "land")  # never `drop`, `clean` nor `init`


def _codex_rule(path: Path) -> bool:
    """A project rule, which codex reads once it trusts the project; `allow` runs those verbs outside its sandbox.
    Written where nothing stands: a file there is his, or this one, and stays as it is."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'prefix_rule(pattern = ["dev-ai", {json.dumps(list(VERBS))}], decision = "allow")\n',
                    encoding="utf-8")
    return True


def _grant(root: Path) -> dict[str, str]:
    """The harnesses' rules for this repository, so the flow runs unprompted; `written` is not `granted`. Claude Code
    gets none (its trust prompt warned about them), nor opencode (its last matching rule wins: ours undoes a deny)."""
    report: dict[str, str] = {}
    for name, write in ((".codex/rules/dev-ai.rules", _codex_rule),):
        path, created, parts = root / name, not (root / name).exists(), Path(name).parts
        try:  # a link on the way, `.codex` to the operator's own, would make this rule a user-wide one
            if any(root.joinpath(*parts[:depth]).is_symlink() for depth in range(1, len(parts) + 1)):
                raise ValueError("a symlink, and a write would follow it")
            written = write(path)
        except (OSError, ValueError) as error:  # not plain JSON, or a write that fails: never a failed init
            report[name] = f"left as it is ({error}): the rules are in the README (Permissions)"
            continue
        report[name] = "rules written" + (f", {_exclude(root, name)}" if created else "") if written else "kept"
    return report


def init(cwd: Path, test_cmd: str, globs: list[str] | None = None) -> dict[str, str]:
    """Prepare a repository once: `dev-ai.json`, its `disposable` globs, the note in `AGENTS.md`, `.dev-ai/`
    excluded, the harness's rules for this repository. Whatever is already there is kept as it is."""
    root = gitops.main_root(cwd)
    settings, agents, report = root / "dev-ai.json", root / "AGENTS.md", {}
    existing = agents.read_text(encoding="utf-8") if agents.is_file() else ""
    linked = [path.name for path, done in ((settings, settings.is_file()), (agents, _has_note(existing)))
              if not done and path.is_symlink()]
    if linked:  # codex, reviewing this: the operator's own ~/.claude/CLAUDE.md is such a link, into a vault
        raise TaskError(
            f"{', '.join(linked)}: a symlink, and init writes inside this checkout only; a write through it "
            "would land elsewhere. Prepare the target yourself, or replace the link with a file, then init again.",
            "symlink")
    if settings.is_file():  # what is there stands, and the report says what it is: `kept` alone read as
        declared = config(root).get("test_command")  # prepared even where no check could ever run (Opus, task 005)
        report["dev-ai.json"] = f"kept, running `{declared}`" if declared else "kept, but it declares no test_command"
    elif not test_cmd:
        raise TaskError(
            "no dev-ai.json and no --test-command. Independent tests are the one check that is never skipped: "
            "`dev-ai init --test-command \"<the repository's suite>\"`, one command, run in the task worktree.",
            "no_test_command")
    else:
        settings.write_text(json.dumps({"test_command": test_cmd}, indent=2) + "\n", encoding="utf-8")
        report["dev-ai.json"] = "written"
    held = read_json(settings)  # the agent's globs beside what is there, never over a set key nor an unread file
    if globs and held and not held.get("disposable") and not settings.is_symlink():  # an empty list declares nothing
        settings.write_text(json.dumps({**held, "disposable": globs}, indent=2) + "\n", encoding="utf-8")
    now = read_json(settings).get("disposable")
    report["disposable"] = (f"{'kept' if held.get('disposable') else 'added'} ({len(now)})" if now else
                            "none declared: pass what the suite writes and git ignores, no secret, as --disposable")
    if _has_note(existing):
        report["AGENTS.md"] = "kept"
    else:
        head = existing.rstrip("\n") + "\n\n" if existing else "# AGENTS.md\n\n"
        agents.write_text(head + NOTE_HEADING + "\n\n" + _note(), encoding="utf-8")
        report["AGENTS.md"] = "note appended" if existing else "created with the note"
    report[".dev-ai/"] = _exclude(root)
    return {**report, **_grant(root)}


def _keep_ignored(root: Path, worktree: Path, directory: Path) -> list[str]:
    """Before a worktree goes, its ignored files that are not `disposable` move under the task's record: `git worktree
    remove` deletes them without a word, and a `.env` copied in to run the suite is not regenerable: kept, not asked."""
    globs = disposable(root)
    kept = [path for path in gitops.ignored_files(worktree)
            if not any(fnmatchcase(f"{worktree.name}/{path}", glob) for glob in globs)]
    for path in kept:
        target = directory / "kept" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(worktree / path), str(target))
    return kept


def _read_spec(cwd: Path, spec: str) -> str:
    """The short contract the reviewer judges against, the operator's or a plan mode's; dev-ai plans nothing."""
    try:
        text = (cwd / spec).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise TaskError(f"cannot read the spec '{spec}': {error}. Name a text file, or start without --spec.",
                        "bad_spec") from None
    if (lines := len(text.splitlines())) > MAX_SPEC_LINES:
        raise TaskError(f"the spec has {lines} lines, {MAX_SPEC_LINES} at most. It states invariants and decisions, "
                        "not a plan: cut it, or start without --spec.", "bad_spec")
    return text


def start(cwd: Path, slug: str, goal: str, paths: list[str], base: str | None, author: str,
          spec: str | None = None, delivery: str = "commit", author_model: str = "") -> Task:
    root = gitops.main_root(cwd)
    if not valid_slug(slug):
        raise TaskError(
            f"'{slug}' is not a task name: lowercase letters, digits, '.', '_' or '-', 64 at most.", "bad_name"
        )
    if author != "human" and not author_model.strip():  # init-command, 2026-09-20: with the other harnesses out,
        raise TaskError(  # the fallback to the author's own harness was refused, no model being recorded to differ from
            f"`{author}` writes this patch with which model? Pass its id with --author-model (claude-fable-5-1, "
            "gpt-6-astra…): without it, a review by this harness has no model to differ from and is refused, "
            "which leaves no reviewer when the other harnesses are unavailable.", "no_author_model")
    if task_dir(root, slug).exists():
        raise TaskError(
            f"task '{slug}' already exists. Pick another name, or see it with `dev-ai status`.", "task_exists"
        )
    spec_text = _read_spec(cwd, spec) if spec else ""
    base_ref = base or config(root).get("base") or gitops.current_branch(root)
    base_sha = gitops.tip(root, base_ref)
    worktree = (state_dir(root) / "worktrees").resolve() / slug  # in the checkout the agent may write to (task 003)
    task = Task(slug, goal, paths, base_ref, base_sha, author, str(worktree), number=next_number(root),
                author_model=author_model.strip(), delivery=delivery)
    worktree.parent.mkdir(parents=True, exist_ok=True)
    gitops.git(root, "worktree", "add", "-b", task.branch, str(worktree), base_sha)
    _exclude(root)
    save(root, task)
    if spec_text:  # kept with the task in the main checkout: a patch cannot rewrite what it is judged against
        (task_dir(root, slug) / "spec.md").write_text(spec_text, encoding="utf-8")
    return task


def scope_add(cwd: Path, slug: str, paths: list[str], reason: str) -> Task:
    """A file the goal turns out to need joins the scope, with the reason on record: the reviewer reads every widening.
    With no path, the reason is a decision taken since `start`, dated, which the reviewer reads too (2026-11-06:
    settled points came back as findings). The harness's prompt is where the operator says no."""
    root = gitops.main_root(cwd)
    task = load(root, slug)
    if not reason.strip():
        raise TaskError(f"widening '{task.label}' needs a --reason, and recording a decision its text: a widening "
                        "without a recorded reason is the bookkeeping this tool exists to keep.", "no_scope")
    task.scope_paths.extend(path for path in paths if path not in task.scope_paths)
    task.scope_history.append({"at": now(), "added": paths, "reason": reason})
    save(root, task)
    return task


def check(cwd: Path, slug: str) -> dict[str, Any]:
    root = gitops.main_root(cwd)
    task = load(root, slug)
    patch, blockers = patch_of(task, worktree := worktree_of(root, task))
    tests = None if blockers else _run_tests(root, task, worktree, patch, blockers)
    if tests and (tests["exit_code"] is None  # stopped on a move: void even if a trap put the bytes back (codex)
                  or gitops.fingerprint(worktree, patch["base_sha"]) != patch["patch_sha256"]):
        blockers.append(("patch_moved", "the patch changed while the tests ran, so they did not test this patch "
                         "(stopped there). Check again once the edit is done; add what tests write to .gitignore."))
    result = {"task": slug, "checked_at": now(), **patch, "tests": tests,
              "blockers": [message for _, message in blockers], "blocker_kinds": [kind for kind, _ in blockers],
              "verdict": "pass" if not blockers else "fail"}
    (task_dir(root, slug) / "check.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def _moved(worktree: Path, patch: dict[str, Any]) -> bool:
    """Whether the patch is no longer the one checked: asked while the tests run, so a void run ends (point 6c)."""
    try:
        return gitops.fingerprint(worktree, patch["base_sha"]) != patch["patch_sha256"]
    except gitops.GitError:  # unreadable for a moment, during an edit: asked again, and read once the tests end
        return False


def _run_tests(root: Path, task: Task, worktree: Path, patch: dict[str, Any],
               blockers: Blockers) -> dict[str, Any] | None:
    command = test_command(root)
    if not command:
        blockers.append(("no_test_command", 'no test command. Independent tests are the one check that is never '
                         'skipped: put {"test_command": "…"} in dev-ai.json at the repository root.'))
        return None
    timeout_s = int(config(root).get("test_timeout") or testgate.DEFAULT_TIMEOUT_S)
    tests = testgate.run(command, worktree, task.slug, task_dir(root, task.slug) / "test.log", timeout_s,
                         lambda: _moved(worktree, patch))
    if tests["timed_out"]:
        blockers.append(("tests_timeout", f"tests timed out after {timeout_s}s (test_timeout). Log: {tests['log']}"))
    elif tests["exit_code"]:  # None: stopped, the patch moved
        blockers.append(("tests_failed", f"tests failed (exit {tests['exit_code']}). Log: {tests['log']}"))
    return tests


def by_severity(findings: list[dict[str, Any]]) -> dict[str, int]:
    return {rank: sum(finding["severity"] == rank for finding in findings)
            for rank in ("critical", "high", "medium", "low")}


def summary(reviewed: dict[str, Any]) -> str:
    """One line about the review: verdict, reviewer, findings by severity, where to read them."""
    counts = [f"{count} {severity}" for severity, count in by_severity(reviewed["findings"]).items()]
    return (f"{reviewed['verdict']} by {reviewed['reviewer']}: {', '.join(counts)} "
            f"({Path(reviewed['log']).with_name('review.md')})")


def _require_pass(slug: str, reviewed: dict[str, Any], needs: list[str]) -> None:
    """A patch that changes behaviour lands only with a passing review of this exact patch. Weighed again: a pass
    recorded over a refuted finding before its reviewer re-read it (land --approve, until 2026-10-27) awaits it."""
    verdict, reason = reviewed.get("verdict"), reviewed.get("reason", "")
    if verdict in ("pass", "pending"):
        verdict, reason = review.weigh(reviewed["findings"])
    if verdict == "fail":
        raise TaskError(f"the review failed this patch: {reason}", "review_failed")
    if verdict == "pending":
        raise TaskError(f"the review of this patch has {reason}", "review_pending")
    if verdict == "unavailable":
        raise TaskError(f"the reviewer was unavailable: {reason}", "review_unavailable")
    if verdict != "pass":
        raise TaskError(f"this patch changes {len(needs)} file(s) that are not descriptive documentation "
                        f"({', '.join(needs[:3])}{'…' if len(needs) > 3 else ''}) and no review of it is recorded. "
                        f"Run `dev-ai review --task {slug}`, then land.", "review_missing")


def land(cwd: Path, slug: str, message: str | None, merge: bool) -> dict[str, Any]:
    root = gitops.main_root(cwd)
    task = load(root, slug)
    worktree = Path(task.worktree)
    checked = checked_now(root, task)
    if merge and task.delivery != "merge":
        raise TaskError(f"the mandate of '{task.label}' is to commit, not to merge (a task opened before mandates "
                        f"existed, or with --delivery commit). Land without --merge, then merge it yourself: "
                        f"`git merge --no-ff {task.branch}`.", "no_mandate")
    if merge and checked["base_sha"] != gitops.tip(root, task.base_ref):  # a commit merges nothing, whatever the base
        raise TaskError(f"'{task.base_ref}' moved since the patch was checked: what was tested is not what would be "
                        f"merged. In the worktree: `git merge {task.base_ref}`, then `dev-ai check` again.",
                        "stale_base")
    needs = list(checked.get("needs_review") or [])
    reviewed = review.standing(root, slug, checked)
    if needs:
        _require_pass(slug, reviewed, needs)
    tests = checked.get("tests") or {}
    print(
        f"Landing '{task.label}': {task.goal}\n  files   {', '.join(checked['changed_files'])}\n"
        f"  review  {summary(reviewed) if reviewed else 'not run: descriptive documentation only'}\n"
        f"  tests   exit {tests.get('exit_code')} in {tests.get('duration_s')} s\n"
        f"  message {message or '(nothing to commit)'}"
        + (f"\n  then    merge into {task.base_ref} and remove the worktree" if merge else "")
    )
    if merge:
        _require_mergeable(root, task, checked["changed_files"])
    if gitops.git(worktree, "status", "--porcelain").strip():
        if not message:
            raise TaskError(
                "uncommitted changes and no message. Pass one with -m \"<type>: <description>\".", "no_message"
            )
        gitops.git(worktree, "add", "-A")
        gitops.git(worktree, "commit", "-m", message)
    # who read it and the model asked for (review.log, routine of 2026-09-28); a review naming nobody lands nothing
    record = {"task": slug, "landed_at": now(), "head_sha": gitops.git(worktree, "rev-parse", "HEAD").strip(),
              "patch_sha256": checked["patch_sha256"], "needs_review": needs,
              "review": reviewed.get("verdict", "not_run"), "reviewer": reviewed["reviewer"] if reviewed else "",
              "requested_model": reviewed["requested_model"] if reviewed else "", "merged": False, "kept": []}
    landing = task_dir(root, slug) / "landing.json"
    if merge:
        gitops.git(root, "merge", "--no-ff", "-m", f"merge {task.branch}: {task.goal}", task.branch)
        record["merged"] = True  # the merge is the delivery: on record before a cleanup that may fail
        landing.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        record["kept"] = _keep_ignored(root, worktree, task_dir(root, slug))
        gitops.git(root, "worktree", "remove", str(worktree))
        gitops.git(root, "branch", "-d", task.branch)
    landing.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def drop(cwd: Path, slug: str, destroy: bool = False) -> dict[str, Any]:
    """Abandon a task: remove its worktree and branch, keep its record. Work that lives nowhere else (uncommitted,
    or on the unmerged branch) goes only on `--destroy`; ignored files that are no cache are kept under the record."""
    root = gitops.main_root(cwd)
    task = load(root, slug)
    worktree = Path(task.worktree)
    branch = gitops.git(root, "branch", "--list", task.branch).strip()
    unsaved = gitops.git(worktree, "status", "--porcelain").splitlines() if worktree.is_dir() else []
    base = gitops.git(root, "rev-parse", "--revs-only", task.base_ref).strip()  # gone: dropped, landed (bench, 10-14)
    merged = base and gitops.git(root, "branch", "--list", "--merged", base, task.branch).strip()
    lost_work = bool(unsaved or (branch and not merged))
    if lost_work and not destroy:
        where = f"merged into {task.base_ref}" if merged else "on no other branch"
        raise TaskError(f"dropping '{task.label}' would destroy {len(unsaved)} uncommitted file(s) in {worktree} and "
                        f"the branch {task.branch} ({where}). Save what matters, or run `dev-ai drop {slug} "
                        "--destroy`.", "lost_work")
    kept = _keep_ignored(root, worktree, task_dir(root, slug)) if worktree.is_dir() else []
    if worktree.is_dir():
        gitops.git(root, "worktree", "remove", "--force", str(worktree))
    gitops.git(root, "worktree", "prune")
    if branch:
        gitops.git(root, "branch", "-D", task.branch)
    record = {"task": slug, "dropped_at": now(), "lost_work": lost_work, "kept": kept}
    (task_dir(root, slug) / "dropped.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def clean(cwd: Path, apply: bool) -> int:
    """After merges: landed worktrees, then the databases `test_databases` names; two scripts, dry until --yes."""
    root, scripts, yes = gitops.main_root(cwd), Path(__file__).resolve().parents[1] / "scripts", ["--yes"] * apply
    under, pattern = (state_dir(root) / "worktrees").resolve(), config(root).get("test_databases")
    base = config(root).get("base") or gitops.current_branch(root)
    caches = [arg for glob in disposable(root) for arg in ("--ignore", glob)] + ["--tasks", str(under.parent / "tasks")]
    code = subprocess.run(["bash", str(scripts / "clean-worktrees.sh"), "--base", base, "--under", str(under),
                           *caches, *yes], cwd=root).returncode if under.is_dir() else 0
    if not pattern:
        print("test databases: none named; set `test_databases`, a regex of their names, in dev-ai.json")
        return code
    return subprocess.run(["bash", str(scripts / "drop-test-dbs.sh"), "--match", pattern, *yes]).returncode or code


def _require_mergeable(root: Path, task: Task, paths: list[str]) -> None:
    """git's own preconditions, checked before anything is committed: nothing staged, and no
    file of the patch changed, untracked or ignored in the main checkout. Other work there stays.
    Ignored counts: git overwrites an ignored file without a word, and a `.env` is one."""
    branch = gitops.current_branch(root)
    if branch != task.base_ref:
        raise TaskError(f"--merge needs the main checkout on '{task.base_ref}', it is on '{branch}'. "
                        f"Switch it, or land without --merge and merge {task.branch} yourself.", "wrong_branch")
    staged = gitops.git(root, "diff", "--cached", "--name-only").strip()
    present = set(gitops.changed_files(root, "HEAD")) | set(gitops.ignored_files(root))
    # A path, or a directory above or below it: an ignored file `docs` stands where the patch's
    # `docs/a.md` goes, an ignored `notes.md/` where its `notes.md` goes (codex, reviewing this patch).
    clashes = sorted(path for path in paths if any(
        there == path or there.startswith(path + "/") or path.startswith(there + "/") for there in present))
    if staged or clashes:
        raise TaskError(f"--merge would collide in the main checkout with {', '.join(clashes) or 'staged changes'}, "
                        "which git would overwrite or refuse. Commit, stash or move them there, or land without "
                        "--merge.", "dirty_checkout")


def _check_state(root: Path, record: dict[str, Any], checked: dict[str, Any], landed: dict[str, Any]) -> str:
    """pass, fail, stale, merged or -: a pass against the worktree now or, landed, in its base or the repository's."""
    if checked.get("verdict") != "pass":
        return checked.get("verdict", "-")
    try:
        names = (record["base_ref"], config(root).get("base") or gitops.current_branch(root)) if landed else ()
        bases = [sha for name in names for sha in gitops.git(root, "rev-parse", "--revs-only", name).split()]  # or gone
        if bases and not gitops.git(root, "rev-list", "-1", landed["head_sha"], *(f"^{b}" for b in bases)).strip():
            return "merged"
        checked_now(root, from_record(record))
        return "pass"
    except (TaskError, TypeError, gitops.GitError):
        return "stale"


def _patch_now(root: Path, record: dict[str, Any]) -> dict[str, Any]:
    """An open task's patch as it stands, for the review read before its check passed; {} when it cannot be read."""
    try:
        return patch_of(task := from_record(record), worktree_of(root, task))[0]
    except (TaskError, TypeError, gitops.GitError):
        return {}


def _next(state: str, check: str, needs: list[str], reviewed: str, moved: str) -> str:
    if state != "open":
        return "-"
    if check != "pass":
        return "check"
    if moved:  # `land` refuses a moved base at once, and a review of a patch to check again is a wasted call
        return f"git merge {moved}, then check"
    if needs and reviewed != "pass":
        return {"pending": "review --resolve", "fail": "fix, then check"}.get(reviewed, "review")  # refuted: review
    return "land"


def status(cwd: Path) -> list[dict[str, Any]]:
    """Every task, its evidence confronted with the repository as it is, and the next useful step."""
    root = gitops.main_root(cwd)
    rows = []  # a directory without task.json is no task: Claude Code writes `.claude` there (the bench, 2026-10-14)
    for directory in (path.parent for path in sorted((state_dir(root) / "tasks").glob("*/task.json"))):
        task, checked, landed = (read_json(directory / name) for name in ("task.json", "check.json", "landing.json"))
        state = ("merged" if landed.get("merged") else "dropped" if (directory / "dropped.json").is_file()
                 else "committed" if landed else "open")
        check = (_check_state(root, task, checked, landed) if state in ("open", "committed")
                 else checked.get("verdict", "-"))
        state, check = ("merged", "pass") if check == "merged" else (state, check)
        patch = checked if check == "pass" else _patch_now(root, task) if state == "open" else {}
        standing = review.standing(root, directory.name, patch) if patch else {}  # a review runs beside its check
        reviewed = standing.get("verdict") or ("stale" if (directory / "review.json").is_file() else "-")
        base = task.get("base_ref", "")  # asked of an open, checked task to merge only: its base resolved already
        moved = (state == "open" and check == "pass" and task.get("delivery") == "merge"  # a commit waits for no base
                 and checked.get("base_sha") != gitops.tip(root, base))
        rows.append({"task": directory.name, "number": task.get("number", 0), "goal": task.get("goal", ""),
            "state": state, "check": check, "review": reviewed,
            "hours": _hours(task.get("created_at"), landed.get("landed_at")),
            "reviewer": (f"{standing.get('reviewer', '?')}:{standing['requested_model'] or 'default'}"
                         if standing else "-"),  # of the review that stands, the one the `review` column reads
            "next": _next(state, check, checked.get("needs_review") or [],
                          "refuted" if review.weigh(standing.get("findings") or [])[1] == review.AWAIT else reviewed,
                          base if moved else ""),
        })
    return rows


def _hours(start: Any, end: Any) -> float | None:  # none for a task merged by hand; a malformed time, none, no crash
    try:
        return (datetime.fromisoformat(end[:19]) - datetime.fromisoformat(start[:19])).total_seconds() / 3600
    except (TypeError, ValueError):  # bookkeeping fails open, as read_json does
        return None


def tally(rows: list[dict[str, Any]]) -> str:  # the line `status` ends with, to track use by
    n, hours = [row["state"] for row in rows].count, [row["hours"] for row in rows if row["hours"] is not None]
    return (f"{len(rows)} tasks: {n('merged') + n('committed')} landed, {n('open')} open, {n('dropped')} dropped;"
            f" median start to landing {round(statistics.median(hours), 1) if hours else '-'} h;"
            f" {sum(row['goal'].startswith('Fixes-task:') for row in rows)} Fixes-task")
