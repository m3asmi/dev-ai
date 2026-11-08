"""The one model call: an independent review of the exact patch, beside its check.

On the bench a *different* model caught what same-provider stages had passed, hence `_independent`. One attempt:
anything but a well-formed answer is `unavailable`, and the harness runs the command again."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from . import gitops
from .task import Task, TaskError, config, decisions, load, now, patch_of, standing, task_dir, worktree_of, write_review

REVIEWERS, DEFAULT_TIMEOUT_S, RESOLUTIONS = ("codex", "claude", "opencode"), 900, ("confirmed", "refuted")
DEFAULT_EFFORT, QUIET = "high", ("--disable", "plugins", "--disable", "apps")  # codex: they act outside its sandbox
LOOK = {"*": "deny", "grep": "allow", "glob": "allow", "list": "allow",  # MCP and project tools too (1.18.31)
        "read": {"*": "allow", "*.env": "deny", "*.env.*": "deny"}}  # the last matching rule wins: `*` first
READ_ONLY = json.dumps({"permission": LOOK, "agent": {"plan": {"permission": LOOK}}})  # past a project's grant
BLOCKING, SEVERITIES = {"critical", "high"}, {"critical", "high", "medium", "low"}
AWAIT = "refuted critical or high finding(s) await the reviewer: `dev-ai review` again sends it your evidence."

QUESTIONS = """\
You review this patch; who wrote it is not stated. The working directory holds
the patched code; you may read it, and you change nothing.

Answer in this order:
1. Does the patch reach the goal? What did it decide that nobody asked for:
   extra behaviour, changed interfaces, files the goal did not need?
2. Does it break an invariant or a decision stated above, when some were? Name it.
3. Which defects are there: broken access control, injection, data loss, a bypassable
   invariant, a failure unhandled or silenced, a guard removed, a call to what does not
   exist, a fix that misses the sibling cases, a test that cannot fail or was weakened?
No style remarks. Every finding names where, the scenario that fails, and the evidence.

Answer with one JSON object and nothing else, no prose, no code fence:
{"verdict": "pass"|"fail", "findings": [{"severity": "critical|high|medium|low", "file": "path", \
"line": 0, "claim": "what is wrong", "scenario": "the inputs and state, then the wrong outcome", \
"evidence": "the lines or the reasoning that show it"}]}
"critical" and "high" mean: must be fixed before this lands. An empty findings list is a valid answer."""
REEXAM = """\
You reviewed this patch and raised the findings below; its author refuted each with the evidence quoted. You may
read the patched code in the working directory and change nothing. Withdraw a finding only if the evidence, checked
against the code, shows it wrong; else maintain it. One JSON object, no prose, no fence, one answer per finding:
{"answers": [{"finding": 1, "answer": "withdrawn"|"maintained", "why": "what in the code decided it"}]}"""


def _argv(reviewer: str, worktree: Path, answer: Path, model: str, effort: str) -> list[str]:
    """Flags of `codex exec` 0.163.0, `claude` 2.1.311, `opencode run` 1.18.31 (2.x: _spawn): read-only, no MCP, no
    bypass, brief on stdin, model and effort named; opencode's plan agent and READ_ONLY deny writes, stdout answers."""
    if reviewer == "opencode":
        return ["opencode", "run", "--agent", "plan", "--dir", str(worktree), "-m", model, "--variant", effort]
    if reviewer == "codex":  # each MCP server is turned off by _spawn, which lists them
        argv = ["codex", "exec", "--sandbox", "read-only", "--ephemeral", *QUIET, "-C", str(worktree)]
        return [*argv, "-o", str(answer), "-m", model, "-c", f'model_reasoning_effort="{effort}"', "-"]
    argv = ["claude", "-p", "--permission-mode", "plan", "--tools", "Read,Grep,Glob", "--strict-mcp-config"]
    return [*argv, "--no-session-persistence", "--model", model, "--effort", effort]


def _spawn(argv: list[str], brief: str, cwd: Path, timeout_s: int) -> subprocess.CompletedProcess[str]:
    """The process calls of a review, codex's list of MCP servers first. Tests replace it."""
    env = {key: val for key, val in os.environ.items() if key != "ANTHROPIC_API_KEY"}  # the login, never the key
    env["OPENCODE_CONFIG_CONTENT"], env["PWD"] = READ_ONLY, str(cwd)  # after a project's config; 2.x's directory
    probe = argv[0] == "opencode" and subprocess.run([argv[0], "-v"], cwd=cwd, env=env, capture_output=True, timeout=9)
    if probe and b"v2." in probe.stdout:  # the version asked under the review's own env and directory (codex, 005)
        argv[4:] = ["--standalone", "-m", f"{argv[7]}#{argv[9]}"]  # 2.2.6: no --dir nor --variant (2026-11-08)
    if argv[0] == "codex":  # ctx_execute ran the patch it reviewed (an operations repository, 2026-10-27)
        out = subprocess.run(["codex", *QUIET, "mcp", "list", "--json"], cwd=cwd, capture_output=True, check=True,
                             timeout=timeout_s)  # a list of servers, else `+ []` below raises TypeError
        argv[2:2] = [a for s in json.loads(out.stdout) + [] for a in ("-c", f"mcp_servers.{s['name']}.enabled=false")]
    return subprocess.run(argv, input=brief, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout_s)


def _ask(argv: list[str], brief: str, worktree: Path, timeout_s: int) -> tuple[str, str, str]:
    text = lambda value: value.decode("utf-8", "replace") if isinstance(value, bytes) else value or ""  # noqa: E731
    try:
        done = _spawn(argv, brief, worktree, timeout_s)
    except subprocess.TimeoutExpired as error:
        return text(error.stdout), text(error.stderr), f"`{argv[0]}` timed out after {timeout_s}s (review_timeout)"
    except (OSError, ValueError, TypeError, KeyError, subprocess.CalledProcessError) as error:  # codex's server list
        return "", str(error), f"`{argv[0]}` could not be started"
    return done.stdout, done.stderr, "" if done.returncode == 0 else f"`{argv[0]}` exited {done.returncode}"


def _brief(task: Task, patch: dict[str, Any], worktree: Path, spec: str, base: str, questions: str) -> str:
    """Goal, decisions, scope, what needs the review, questions, then the whole patch, deletions included."""
    spec, scope = spec.strip(), [f"- {path}" for path in task.scope_paths] + [  # a decision: settled, not to raise
        f"- {'widened' if e['added'] else 'decided'} on {e['at']}: {', '.join(e['added']) or 'settled'} ({e['reason']})"
        for e in task.scope_history]
    diff = [gitops.git(worktree, "diff", "--no-renames", base, "--")]
    diff += [f"--- new untracked file: {path}\n{text}" for path, text in gitops.untracked_text(worktree).items()]
    return "\n\n".join([f"GOAL OF THE TASK\n{task.goal}",
        *([f"WHAT WAS DECIDED, the invariants and decisions the patch must respect\n{spec}"] if spec else []),
        "SCOPE, the paths the task may touch\n" + "\n".join(scope),
        "WHAT NEEDS THE REVIEW, the changed files that are not descriptive documentation\n"
        + (", ".join(patch.get("needs_review") or []) or "none"),
        questions, f"THE PATCH, against {base}\n" + "\n".join(diff),
        "Answer with the JSON object only."])


def _objects(text: str) -> list[Any]:
    """Every JSON value opening on `{` in the output, fenced or not, prose around it."""
    decoder, found, at = json.JSONDecoder(), [], text.find("{")
    while at != -1:
        try:
            candidate, end = decoder.raw_decode(text, at)
            found.append(candidate)
        except json.JSONDecodeError:
            end = at + 1
        at = text.find("{", end)
    return found


def _findings(text: str) -> list[dict[str, Any]] | None:
    """A well-formed answer's findings or None: any JSON object in the output; the most blocking stands."""
    answers = []
    for candidate in _objects(text):
        if isinstance(candidate, dict) and candidate.get("verdict") in ("pass", "fail"):
            found = candidate.get("findings")
            if not isinstance(found, list) or (candidate["verdict"] == "fail" and not found) or not all(
                    isinstance(item, dict) and item.get("severity") in SEVERITIES for item in found):
                return None  # malformed, or a `fail` that names nothing: unavailable, and no other object stands in
            answers.append(found)
    return max(reversed(answers), key=lambda found: sum(item["severity"] in BLOCKING for item in found), default=None)


def _answers(text: str, count: int) -> list[tuple[str, str]] | None:
    """`withdrawn` or `maintained` for each of `count` refuted findings, or None; the most maintaining stands."""
    valid = []
    for candidate in _objects(text):
        rows = candidate.get("answers") if isinstance(candidate, dict) else None
        rows = rows if isinstance(rows, list) and all(isinstance(row, dict) for row in rows) else []
        got = {row["finding"]: row for row in rows if type(row.get("finding")) is int and row.get("answer") in (
            "withdrawn", "maintained") and isinstance(row.get("why"), str) and row["why"].strip()}  # True is not 1
        if len(rows) == count and set(got) == set(range(1, count + 1)):
            valid.append([(got[n]["answer"], got[n]["why"]) for n in range(1, count + 1)])
    return max(reversed(valid), key=lambda found: [answer for answer, _ in found].count("maintained"), default=None)


def weigh(findings: list[dict[str, Any]]) -> tuple[str, str]:
    """fail on a confirmed blocker; pending while one awaits evidence, then the reviewer once refuted; else pass."""
    resolutions = {finding.get("resolution") for finding in findings if finding["severity"] in BLOCKING}
    if "confirmed" in resolutions:
        return "fail", "a confirmed critical or high finding: fix it, then check and review again."
    if resolutions - {"refuted", "withdrawn"}:
        return "pending", ("critical or high finding(s) await evidence: `dev-ai review --resolve <n> "
                           "--resolution confirmed|refuted --evidence …` for each, in review.md order.")
    return ("pending", AWAIT) if "refuted" in resolutions else ("pass", "")


def _independent(task: Task, reviewer: str, model: str) -> None:
    """Another harness, or the author's naming another model than the recorded one (the owner, 2026-09-20). A model
    is named every time (2026-09-29): opencode's free default passed the bench's task-072 and 089 with no finding."""
    if not model:
        raise TaskError(f"`{reviewer}` reviews with which model? Name one with --model, never a default.", "no_model")
    if task.author_model and model.rsplit("/", 1)[-1] == task.author_model.rsplit("/", 1)[-1]:
        raise TaskError(f"`{model}` is the author's own model: name another with --model.", "same_reviewer")
    if reviewer == task.author and not task.author_model:
        raise TaskError(f"`{reviewer}` wrote this patch, and `start --author-model` recorded no model for the "
                        "reviewer's to differ from: another harness reviews it.", "same_reviewer")


def _call(task: Task, patch: dict[str, Any], directory: Path, reviewer: str, model: str, effort: str,
          questions: str) -> tuple[str, str, float]:
    """One reviewer, one run, every byte kept: TASK-068 threw the stderr away, evals-oracle-068 overwrote a retry."""
    worktree, base = Path(task.worktree), patch["base_sha"]
    timeout_s = int(config(gitops.main_root(worktree)).get("review_timeout") or DEFAULT_TIMEOUT_S)
    answer, log_path = directory / "review.answer", directory / "review.log"
    answer.unlink(missing_ok=True)
    argv = _argv(reviewer, worktree, answer, model, effort)
    spec = directory / "spec.md"  # recorded by `start` in the main checkout, out of the patch's reach
    brief = _brief(task, patch, worktree, spec.read_text(encoding="utf-8") if spec.is_file() else "", base, questions)
    if gitops.fingerprint(worktree, base) != patch["patch_sha256"]:  # a test beside it wrote: send what was scanned
        raise TaskError("the patch changed between its scan and the brief, a run beside the review writing to it: "
                        "nothing was sent. Review it again once it holds still.", "patch_moved")
    started, (stdout, stderr, failure) = time.monotonic(), _ask(argv, brief, worktree, timeout_s)
    moved = gitops.fingerprint(worktree, base) != patch["patch_sha256"] and "the patch changed while it was reviewed"
    written = answer.read_text(encoding="utf-8", errors="replace") if answer.is_file() else ""
    answer.unlink(missing_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"$ {now()} patch {patch['patch_sha256'][:12]} {' '.join(argv)}\n{failure or 'exit 0'}\n"
                  f"--- answer file\n{written}\n--- stdout\n{stdout}\n--- stderr\n{stderr}\n")
    return written or stdout, failure or moved or "", round(time.monotonic() - started, 1)


def _reexamine(task: Task, patch: dict[str, Any], directory: Path, kept: dict[str, Any], reviewer: str, model: str,
               effort: str) -> dict[str, Any]:
    """Each refutation goes back to the reviewer, never the operator (2026-10-27: four landed on his word came back as
    Fixes-tasks). `maintained` confirms it, `withdrawn` settles it, anything else leaves it open."""
    refuted = [item for item in kept["findings"] if item["severity"] in BLOCKING and item["resolution"] == "refuted"]
    claims = "".join(f"\n\nFINDING {n}: {item.get('file', '?')}:{item.get('line', 0)} {item.get('claim', '')}\n"
                     f"Scenario: {item.get('scenario', '')}\nYour evidence: {item.get('evidence', '')}\nRefuted by "
                     f"the author: {item['resolution_evidence']}" for n, item in enumerate(refuted, 1))
    text, failure, duration = _call(task, patch, directory, reviewer, model, effort, REEXAM + claims)
    answers = None if failure else _answers(text, len(refuted))
    if answers is None:
        return {**kept, "verdict": "pending", "reason": f"{failure or 'the answer was not the JSON asked for'}: "
                f"the refuted finding(s) stay open; review again. Full reviewer output: {directory}/review.log."}
    for item, (answer, why) in zip(refuted, answers, strict=True):
        item.update(resolution="confirmed" if answer == "maintained" else answer, reexamined_why=why,
                    reexamined_by=f"{reviewer}:{model}", resolved_at=now())
    return {**kept, **dict(zip(("verdict", "reason"), weigh(kept["findings"]), strict=True)), "duration_s": duration}


def run(cwd: Path, slug: str, reviewer: str | None, model: str = "", effort: str = DEFAULT_EFFORT) -> dict[str, Any]:
    task = load(root := gitops.main_root(cwd), slug)
    other = "claude" if task.author == "codex" else "codex"  # codex reads claude; with it absent, the author's
    reviewer = reviewer or next((n for n in (other, task.author) if n in REVIEWERS and shutil.which(n)), other)
    patch, blockers = patch_of(task, worktree_of(root, task))  # as it stands: the check may be running beside it
    if blockers:  # what a check refuses before its tests never reaches a reviewer, a secret-bearing file above all
        raise TaskError(" ".join(message for _, message in blockers), blockers[0][0])
    kept, directory = standing(root, slug, patch), task_dir(root, slug)
    verdict, reason = kept.get("verdict"), ""
    if verdict in ("pass", "pending"):  # weighed again: a pass recorded over a refutation before 2026-10-27 is not one
        verdict, reason = weigh(kept["findings"])
    if verdict == "pending" and reason != AWAIT:  # a run of the same patch never erases an open finding
        raise TaskError(f"this patch already has a review whose {reason}", "review_pending")
    if verdict == "fail":  # nor a confirmed one: the patch changes, or the verdict stands
        raise TaskError(f"this patch already has a failed review: {kept['reason']}", "review_failed")
    _independent(task, reviewer, model)
    if verdict == "pending":  # refuted: the same patch goes back to a reviewer, with the author's evidence
        return write_review(directory, _reexamine(task, patch, directory, kept, reviewer, model, effort))
    text, failure, duration = _call(task, patch, directory, reviewer, model, effort, QUESTIONS)
    findings = None if failure else _findings(text)
    if findings is None:  # every reviewer left; the author's harness only against a recorded model
        left = [f"--reviewer {name} --model <{'not ' + task.author_model if name == task.author else 'id'}>"
                for name in REVIEWERS if name != reviewer and (name != task.author or task.author_model)]
        verdict, reason = "unavailable", (f"{failure or 'the answer was not the JSON asked for'}. Full reviewer "
                                          f"output: {directory}/review.log. Run it again"
                                          f"{', or: ' + '; '.join(left) if left else ''}.")
    else:
        findings = [{**item, "resolution": "pending" if item["severity"] in BLOCKING else ""} for item in findings]
        verdict, reason = weigh(findings)
    return write_review(directory, {
        "task": task.slug, "reviewed_at": now(), "patch_sha256": patch["patch_sha256"], "base_sha": patch["base_sha"],
        "reviewer": reviewer, "author": task.author, "requested_model": model, "requested_effort": effort,
        "observed_model": "", "verdict": verdict, "findings": findings or [], "reason": reason,
        "duration_s": duration, "log": str(directory / "review.log"), "decisions": decisions(task)})


def resolve(cwd: Path, slug: str, index: int, resolution: str, evidence: str) -> dict[str, Any]:
    """One finding of the current patch answered with evidence: `refuted` goes to the reviewer, `confirmed` fails."""
    task = load(root := gitops.main_root(cwd), slug)
    kept = standing(root, slug, patch_of(task, worktree_of(root, task))[0])
    if "voided" in kept:
        raise TaskError(f"no review of the current patch: run `dev-ai review --task {slug}` first.", "review_missing")
    if resolution not in RESOLUTIONS or not evidence.strip() or not 1 <= index <= len(kept["findings"]):
        raise TaskError(f"name a finding from 1 to {len(kept['findings'])} (their order in review.md), its "
                        "--resolution confirmed|refuted and the --evidence that decides it: a resolution without "
                        "evidence is the reviewer's word against the developer's.", "bad_resolution")
    if kept["findings"][index - 1].get("reexamined_by"):  # a reviewer read the evidence: no reroll on the same patch
        raise TaskError(f"finding {index} was re-examined by {kept['findings'][index - 1]['reexamined_by']}: its "
                        "answer stands. Fix the patch, then check and review again.", "bad_resolution")
    kept["findings"][index - 1].update(resolution=resolution, resolution_evidence=evidence, resolved_at=now())
    kept["verdict"], kept["reason"] = weigh(kept["findings"])
    return write_review(task_dir(root, slug), kept)
