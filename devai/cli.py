"""Command line. Exit 0: done. Exit 1: blocked, the message says how to recover.
Exit 2: the tool or git itself failed."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from . import __version__, commands, gitops, review
from .task import AUTHORS, DELIVERIES, TaskError, now, resolve, slug_from, state_dir


def _log(cwd: Path, command: str, task: str | None, outcome: str, started: float, detail: dict[str, Any]) -> None:
    """One JSONL row per command. Preparation, run and human-wait times all fall
    out of these timestamps; nothing else is instrumented. Never fails a command.
    The version makes a result attributable to the tool that produced it."""
    try:
        path = state_dir(gitops.main_root(cwd)) / "log.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {"at": now(), "version": __version__, "command": command, "task": task, "outcome": outcome,
               "duration_ms": int((time.monotonic() - started) * 1000), **detail}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
    except (OSError, gitops.GitError):
        pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dev-ai", description="Contain the work, prove the patch.")
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="open a task: branch, worktree, scope, mandate")
    start.add_argument("slug")
    start.add_argument("--goal", required=True)
    start.add_argument("--paths", nargs="+", required=True, help="files, directories or globs the task may touch")
    start.add_argument("--base", help="branch to start from (default: the main checkout's current branch)")
    start.add_argument("--author", default="claude", choices=AUTHORS, help="the harness that writes the patch")
    start.add_argument("--author-model", default="", help="the model that writes the patch; a human author has none")
    start.add_argument("--delivery", default="commit", choices=DELIVERIES, help="what `land` may do; merge is said")
    start.add_argument("--spec", help="a short file of invariants and decisions for the reviewer to judge against")
    for name, text in (("check", "scope, host tests and what needs a review, on the exact patch"),
                       ("review", "one independent review of the patch, beside its check, or resolve a finding"),
                       ("land", "commit the checked patch; --merge to merge and clean up, within the mandate"),
                       ("scope-add", "widen a task's scope, with the reason on record")):
        verb = sub.add_parser(name, help=text)
        verb.add_argument("--task", help="task name or number (default: the task of the current worktree)")
    rev = sub.choices["review"]
    rev.add_argument("--reviewer", choices=review.REVIEWERS, help="default: the other harness than the author's")
    rev.add_argument("--model", default="", help="named for every review, asked of the reviewer's CLI; never the "
                     "author's model")
    rev.add_argument("--effort", default=review.DEFAULT_EFFORT, help="the reasoning effort asked of the reviewer's "
                     "CLI; never its own default")
    rev.add_argument("--resolve", type=int, metavar="N", help="finding N of the current review, in review.md order")
    rev.add_argument("--resolution", choices=review.RESOLUTIONS)
    rev.add_argument("--evidence", default="", help="what shows the finding confirmed or refuted")
    sub.choices["land"].add_argument("-m", "--message", action="append", help="each one a paragraph, as git joins them")
    sub.choices["land"].add_argument("--merge", action="store_true")
    sub.choices["scope-add"].add_argument("paths", nargs="*")
    sub.choices["scope-add"].add_argument("--reason", default="")
    gone = sub.add_parser("drop", help="abandon a task: remove its worktree and branch, keep its record")
    gone.add_argument("slug")
    gone.add_argument("--destroy", action="store_true", help="destroy work that lives nowhere else")
    ready = sub.add_parser("init", help="prepare a repository: dev-ai.json, the AGENTS.md note, .dev-ai/ excluded")
    ready.add_argument("--test-command", default="", help="the suite, one command; needed to write dev-ai.json")
    ready.add_argument("--disposable", action="append", default=[], help="a glob: what the suite writes, git ignores")
    sub.add_parser("status", help="every task, its evidence confronted with the repository, the next step")
    tidy = sub.add_parser("clean", help="after merges: the landed worktrees, then the `test_databases` of dev-ai.json")
    tidy.add_argument("--yes", action="store_true", help="remove them; without it, only list them")
    return parser


def _dispatch(args: argparse.Namespace, cwd: Path) -> tuple[int, str | None, dict[str, Any]]:
    if args.command == "start":
        task = commands.start(cwd, args.slug, args.goal, args.paths, args.base, args.author, args.spec,
                              args.delivery, args.author_model)
        print(f"task {task.label} opened on {task.branch}, delivery {task.delivery}\n"
              f"worktree: {task.worktree}\nDevelop there, then side by side: dev-ai check, dev-ai review")
        return 0, task.slug, {"delivery": task.delivery}
    if args.command == "status":
        for row in commands.status(cwd):
            number = f"{row['number']:03d}" if row["number"] else "  -"
            print(f"{number} {row['task']:<24} {row['state']:<10} check={row['check']:<6} review={row['review']:<12}"
                  f" by={row['reviewer']:<22} next={row['next']:<16} {row['goal']}")
        return 0, None, {}
    if args.command == "init":
        report = commands.init(cwd, args.test_command, args.disposable)
        print("\n".join(f"{item:<12} {state}" for item, state in report.items()))
        return 0, None, report
    if args.command == "clean":
        return commands.clean(cwd, args.yes), None, {"yes": args.yes}
    if args.command == "drop":
        record = commands.drop(cwd, slug := resolve(gitops.main_root(cwd), args.slug), args.destroy)
        print(f"dropped {slug}" + ("; its unmerged work is gone" if record["lost_work"] else "") + _kept(record))
        return 0, slug, {"lost_work": record["lost_work"], "kept": len(record["kept"])}
    slug = slug_from(cwd, args.task)
    if args.command == "scope-add":
        task = commands.scope_add(cwd, slug, args.paths, args.reason)
        print(f"scope of {slug}: {', '.join(task.scope_paths)}")
        return 0, slug, {"added": args.paths}
    if args.command == "check":
        result = commands.check(cwd, slug)
        for blocker in result["blockers"]:
            print(f"BLOCKED: {blocker}")
        print(f"check {result['verdict']}: {len(result['changed_files'])} file(s), "
              f"{len(result['needs_review'])} need(s) a review")
        detail = {"verdict": result["verdict"], "needs_review": len(result["needs_review"]),
                  "blockers": result["blocker_kinds"]}
        return (0 if result["verdict"] == "pass" else 1), slug, detail
    if args.command == "review":
        result = (review.resolve(cwd, slug, args.resolve, args.resolution or "", args.evidence)
                  if args.resolve is not None else review.run(cwd, slug, args.reviewer, args.model, args.effort))
        for index, finding in enumerate(result["findings"], 1):
            print(f"{index}. {finding['severity'].upper()} {finding.get('resolution') or ''}: "
                  f"{finding.get('file', '?')}:{finding.get('line', 0)} {finding.get('claim', '')}")
        print(f"review {result['verdict']} by {result['reviewer']}"
              + (f": {result['reason']}" if result["reason"] else ""))
        detail = {"verdict": result["verdict"], "reviewer": result["reviewer"], "author": result["author"],
                  "model": result["requested_model"], "findings": commands.by_severity(result["findings"])}
        if result["verdict"] != "pass":  # a review that blocked is counted by kind, as every other blocker is
            detail["kind"] = "review_" + {"fail": "failed"}.get(result["verdict"], result["verdict"])
        return (0 if result["verdict"] == "pass" else 1), slug, detail
    record = commands.land(cwd, slug, "\n\n".join(args.message) if args.message else None, args.merge)
    print(f"landed {slug} at {record['head_sha'][:12]}" + (" and merged" if record["merged"] else
          f"; merge when ready: git merge --no-ff dev-ai/{slug}") + _kept(record)
          + "\nonce merged, in the repository: dev-ai clean lists what can go, dev-ai clean --yes removes it")
    return 0, slug, {"merged": record["merged"], "needs_review": len(record["needs_review"]),
                     "review": record["review"], "kept": len(record["kept"])}


def _kept(record: dict[str, Any]) -> str:
    return (f"; {len(record['kept'])} ignored file(s) kept under .dev-ai/tasks/{record['task']}/kept: "
            f"{', '.join(record['kept'][:5])}" if record["kept"] else "")


def _task_name(args: argparse.Namespace, cwd: Path) -> str | None:
    """For the log row of a command blocked before it could name its task."""
    try:
        return getattr(args, "slug", None) or slug_from(cwd, getattr(args, "task", None))
    except (TaskError, gitops.GitError):
        return None


def main(argv: list[str] | None = None, cwd: Path | None = None) -> int:
    cwd, started, args = cwd or Path.cwd(), time.monotonic(), _parser().parse_args(argv)
    task = _task_name(args, cwd)
    try:
        code, task, detail = _dispatch(args, cwd)
        _log(cwd, args.command, task, "ok" if code == 0 else "blocked", started, detail)
        return code
    except TaskError as blocker:  # a command that blocks still leaves its row: the log counts every kind
        print(f"BLOCKED: {blocker}", file=sys.stderr)
        _log(cwd, args.command, task, "blocked", started, {"kind": blocker.kind, "reason": str(blocker)[:200]})
        return 1
    except gitops.GitError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        _log(cwd, args.command, task, "error", started, {"reason": str(error)[:200]})
        return 2


if __name__ == "__main__":
    sys.exit(main())
