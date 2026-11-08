"""Task state, project configuration and scope. Plain JSON, no signatures."""

from __future__ import annotations

import fnmatch
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import gitops, impact

BRANCH_PREFIX = "dev-ai/"
STATE_DIR = ".dev-ai"
MAX_SPEC_LINES = 80  # the cap is the point: dev-pipeline's per-task contracts ran to hundreds of lines
AUTHORS = ("claude", "codex", "opencode", "human")  # who may open a task; one on record loads whoever wrote it
DELIVERIES = ("merge", "commit")  # the mandate `land` obeys: merge into the base, or commit on the branch only
_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_NUMBER = re.compile(r"^(?:task[-_]?)?0*([0-9]{1,6})$", re.IGNORECASE)  # 7, 007, task-007, TASK-7
# Every blocker kind there is. The log counts the ones that fire; one that never does
# is a check to remove. `tests/test_budget.py` holds this list equal to the kinds in use.
KINDS = (
    "no_task", "not_a_task", "ambiguous_task", "bad_name", "no_scope", "no_author_model", "bad_spec",
    "task_exists", "worktree_gone", "empty_patch", "out_of_scope", "secret_in_patch", "patch_moved", "no_test_command",
    "tests_timeout", "tests_failed", "unchecked", "stale_base", "no_message", "wrong_branch", "dirty_checkout",
    "no_mandate", "lost_work", "symlink", "review_failed", "review_pending", "review_unavailable",
    "review_missing", "same_reviewer", "no_model", "bad_resolution",
)


class TaskError(RuntimeError):
    """A blocker the operator can act on. The message says what, why and how; the
    kind is what the log counts, so a check that never fires can be seen and removed."""

    def __init__(self, message: str, kind: str) -> None:
        super().__init__(message)
        self.kind = kind


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


@dataclass
class Task:
    slug: str
    goal: str
    scope_paths: list[str]
    base_ref: str
    base_sha: str
    author: str
    worktree: str
    created_at: str = field(default_factory=now)
    scope_history: list[dict[str, Any]] = field(default_factory=list)
    number: int = 0  # 0: opened before numbering existed, and named by its slug only
    author_model: str = ""  # the model behind the author; '' only for a human, or a task opened before it was required
    # A task opened before mandates existed never agreed to a merge: it loads as `commit`.
    delivery: str = "commit"

    @property
    def branch(self) -> str:
        return BRANCH_PREFIX + self.slug

    @property
    def label(self) -> str:
        return f"{self.number:03d} {self.slug}" if self.number else self.slug


def valid_slug(slug: str) -> bool:
    return bool(_SLUG.match(slug))


def state_dir(root: Path) -> Path:
    return root / STATE_DIR


def task_dir(root: Path, slug: str) -> Path:
    return state_dir(root) / "tasks" / slug


def save(root: Path, task: Task) -> None:
    directory = task_dir(root, task.slug)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "task.json").write_text(json.dumps(asdict(task), indent=2) + "\n", encoding="utf-8")


def from_record(record: dict[str, Any]) -> Task:
    """This release's fields of a record: one an earlier release wrote keeps its own, `profile` until 0.15.0."""
    return Task(**{key: value for key, value in record.items() if key in Task.__dataclass_fields__})


def load(root: Path, slug: str) -> Task:
    path = task_dir(root, slug) / "task.json"
    try:
        return from_record(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        raise TaskError(
            f"no task '{slug}' in {state_dir(root)}. List tasks with `dev-ai status`, "
            f"or open one with `dev-ai start {slug} --goal … --paths … --author-model …`.",
            "no_task",
        ) from None


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def every_task(root: Path) -> list[dict[str, Any]]:
    """Read loosely: numbering puts this on the path of every command, and one unreadable or
    forward-version record must not take the tool down with it."""
    records = (read_json(entry / "task.json") for entry in sorted((state_dir(root) / "tasks").glob("*")))
    return [record for record in records if record.get("slug")]


def next_number(root: Path) -> int:
    return max((int(record.get("number") or 0) for record in every_task(root)), default=0) + 1


def resolve(root: Path, wanted: str) -> str:
    """A task named any way the operator finds natural: its slug, or its number as 7, 007,
    task-007 or TASK-7. A name that fits none, or more than one, is refused, never guessed."""
    digits = _NUMBER.match(wanted)
    # valid_slug first: resolve is the single gate that turns a string into a path under
    # `.dev-ai/tasks/`, and `..` in a name must never reach it.
    named = [wanted] if valid_slug(wanted) and (task_dir(root, wanted) / "task.json").is_file() else []
    numbered = [record["slug"] for record in every_task(root)
                if digits and record.get("number") == int(digits.group(1)) and record["slug"] not in named]
    if len(named + numbered) == 1:
        return (named + numbered)[0]
    if named or numbered:  # a task literally named '007' beside task number 7: say so, never pick
        raise TaskError(f"'{wanted}' names {len(named + numbered)} tasks: {', '.join(named + numbered)}. "
                        "Use one of their names.", "ambiguous_task")
    raise TaskError(f"no task '{wanted}'. List them with `dev-ai status`.", "no_task")


def slug_from(cwd: Path, explicit: str | None) -> str:
    """The task named on the command line, else the one whose worktree we are in."""
    if explicit:
        return resolve(gitops.main_root(cwd), explicit)
    branch = gitops.current_branch(cwd)
    if branch.startswith(BRANCH_PREFIX):
        return branch[len(BRANCH_PREFIX):]
    raise TaskError(
        f"branch '{branch}' is not a dev-ai task. Run this from a task worktree, "
        "or name the task with --task <slug>.",
        "not_a_task",
    )


def config(root: Path) -> dict[str, Any]:
    """`dev-ai.json` and nothing else. dev-pipeline's `dp-project.json` is not read: all five
    surveyed on 2026-09-18 declare an end-to-end suite that one test command would silently drop."""
    return read_json(root / "dev-ai.json")


def disposable(root: Path) -> list[str]:
    """Globs over `<worktree name>/<path>` a removed worktree may lose: caches, then what `init --disposable` recorded
    (a Next.js site kept 49 worktrees for their `.next/`, 2026-10-14). A string is no list: its `*` matches all."""
    declared = config(root).get("disposable")
    caches = ["*.py[co]", "*/__pycache__/*", "*/.*_cache/*", "*/.tox/*", "*/node_modules/*", "*/.venv/*", "*/venv/*"]
    return caches + [glob for glob in declared if isinstance(glob, str)] if isinstance(declared, list) else caches


def test_command(root: Path) -> str:
    return str(config(root).get("test_command") or "").strip()


def worktree_of(root: Path, task: Task) -> Path:
    """The task's worktree, or the blocker, for `check`, `review` and `land` alike: a review of merged task 034 exited 2
    on git's `cannot change to`, and `check` named a branch the merge had deleted. It says what to do in each case and
    tells none apart: three reviews of task 040 found three states guessed wrong, from a record blind to hand merges."""
    worktree, asked = Path(task.worktree), ("rev-parse", "--path-format=absolute", "--git-common-dir")
    try:  # asked of git from inside: a directory answers with the checkout around it, a clone with its own repository
        inside = gitops.git(worktree, *asked, "--show-toplevel", "--abbrev-ref", "HEAD").splitlines()
    except gitops.GitError:
        inside = []
    if inside[:2] == [gitops.git(root, *asked).strip(), str(worktree)]:  # this repository's, at this very path
        if inside[2:] == [task.branch]:
            return worktree
        raise TaskError(f"the worktree of '{task.label}' is on `{inside[2]}`, not on {task.branch}: once what is "
                        f"under way there is done, `git checkout {task.branch}` in it, the branch recreated first if "
                        f"it is gone (`git reflog`, then `git branch {task.branch} <commit>`), and check again.",
                        "wrong_branch")
    raise TaskError(
        f"the worktree of '{task.label}' is gone: git holds no worktree of {task.branch} at {worktree}. First, "
        f"whatever stands there now is not the task's: move it away. Merged, by dev-ai or by hand: nothing is left "
        f"to check, review or land. Not merged: `git worktree prune`, the branch recreated if it is gone too "
        f"(`git reflog`, then `git branch {task.branch} <commit>`), `git worktree add {worktree} {task.branch}`, and "
        f"check again; or close the task with `dev-ai drop {task.slug}`, which asks for --destroy where work would "
        f"be lost.", "worktree_gone")


def checked_now(root: Path, task: Task) -> dict[str, Any]:
    """The passing check of the patch as it stands, or the blocker. Evidence is bound to the exact patch, to the base it
    was checked against and to the test command that judged it: `status` here showed an old pass beside an edited
    worktree, and a pass under another base or another `test_command` proves nothing about this one."""
    checked = read_json(task_dir(root, task.slug) / "check.json")
    worktree = worktree_of(root, task)
    if checked.get("verdict") != "pass":
        why = "no passing check"
    elif "needs_review" not in checked:  # a record from before 0.6.0: its `impact` decides nothing here
        why = "the check predates this release"
    elif checked.get("base_sha") != gitops.merge_base(worktree, task.base_ref):
        why = "the base was merged into the worktree since the check"
    elif gitops.fingerprint(worktree, checked["base_sha"]) != checked.get("patch_sha256"):
        why = "the patch changed since it was checked"
    elif (checked.get("tests") or {}).get("command") != test_command(root):
        why = "the test command changed since the check"
    else:
        return checked
    raise TaskError(f"{why}. Run `dev-ai check --task {task.slug}`: only the exact checked patch is reviewed "
                    "or landed.", "unchecked")


def patch_of(task: Task, worktree: Path) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """The patch as it stands, and what bars it from tests and from a reviewer alike: `check` and `review` run side
    by side since 2026-09-29, and refuse an empty patch, a path outside the scope and a secret for the same reasons."""
    base = gitops.merge_base(worktree, task.base_ref)
    changed = gitops.changed_files(worktree, base)
    patch = {"base_sha": base, "patch_sha256": gitops.fingerprint(worktree, base), "changed_files": changed,
             "needs_review": impact.needs_review(changed)}
    blockers: list[tuple[str, str]] = []
    if not changed:
        blockers.append(
            ("empty_patch", "the patch is empty: nothing differs from the base. Make the change, then check again.")
        )
    stray = outside_scope(changed, task.scope_paths)
    if stray:
        blockers.append((
            "out_of_scope",
            "outside the task scope: " + ", ".join(stray) + ". Revert them, or widen the scope with "
            f"`dev-ai scope-add --task {task.slug} <path> --reason …`, saying why the goal needs them.",
        ))
    leaks = impact.secret_bearing(changed, gitops.added_lines(worktree, base))
    if leaks:
        blockers.append((
            "secret_in_patch",
            "secret-bearing content in the patch: " + ", ".join(leaks) + ". `review` would send it to a model "
            "provider and `land` would commit it. Take it out of the patch (add the file to .gitignore or "
            "untrack it, keep keys out of the code), then check again.",
        ))
    return patch, blockers


def outside_scope(changed: list[str], scope_paths: list[str]) -> list[str]:
    """Changed paths no scope entry covers. An entry is a file, a directory or a glob."""
    patterns = [entry.removeprefix("./").rstrip("/") for entry in scope_paths if entry.strip()]

    def covered(path: str) -> bool:
        return any(
            path == pattern or path.startswith(pattern + "/") or fnmatch.fnmatch(path, pattern)
            for pattern in patterns
        )

    return [path for path in changed if not covered(path)]


def decisions(task: Task) -> int:
    """How many decisions since `start` the task holds: `scope-add` with a reason and no path."""
    return sum(not entry["added"] for entry in task.scope_history)


def standing(root: Path, slug: str, patch: dict[str, Any]) -> dict[str, Any]:
    """The review of this diff, or {}: its fingerprint, on a base that leaves the patch's files as it read them
    (settings-all-counted, 2026-09-29: read and approved twice over one diff; a conflict kept on the task's side
    keeps the bytes over another). A record from before findings carried evidence (no `requested_model`) is none."""
    recorded = read_json(task_dir(root, slug) / "review.json")
    if "requested_model" not in recorded or recorded.get("patch_sha256") != patch.get("patch_sha256"):
        return {}
    if recorded.get("verdict") == "pass" and decisions(load(root, slug)) > recorded.get("decisions", 0):
        return {}  # a pass that never read a decision (codex, task 010); an open or failed finding stays
    under = recorded.get("base_sha") != patch["base_sha"] and gitops.git(
        root, "diff", "--name-only", "--no-renames", recorded["base_sha"], patch["base_sha"], "--",
        *patch["changed_files"]).strip()
    return {} if under else recorded


def write_review(directory: Path, result: dict[str, Any]) -> dict[str, Any]:
    """review.json, the record, and review.md, what the operator reads; `standing` reads the record back."""
    lines = [f"# Review of {result['task']}: {result['verdict']}", "",
             f"Reviewer `{result['reviewer']}`, model requested `{result['requested_model'] or 'default'}`, "
             f"effort `{result.get('requested_effort') or 'default'}`, observed unknown; {result['reviewed_at']}, "
             f"{result['duration_s']} s, patch `{result['patch_sha256'][:12]}`.",
             *(["", result["reason"]] if result["reason"] else [])]
    for index, finding in enumerate(result["findings"], 1):
        state = f" ({finding['resolution'].upper()})" if finding.get("resolution") else ""
        lines += ["", f"## {index}. {finding['severity'].upper()}{state}: {finding.get('file', '?')}:"
                  f"{finding.get('line', 0)}", "", str(finding.get("claim", "")),
                  f"Scenario: {finding.get('scenario', '')}", f"Evidence: {finding.get('evidence', '')}",
                  *([f"Resolved: {finding['resolution_evidence']}"] if finding.get("resolution_evidence") else []),
                  *([f"Re-examined by {finding['reexamined_by']}: {finding['reexamined_why']}"]
                    if finding.get("reexamined_by") else [])]
    (directory / "review.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (directory / "review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result
