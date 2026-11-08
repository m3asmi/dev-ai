"""The independent review: bound to the exact patch, fail closed, re-runnable. No real model runs here."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from conftest import sh

from devai import cli, commands, review
from devai.task import TaskError

LOW = {"severity": "low", "file": "src/app.py", "line": 2, "claim": "name it",
       "scenario": "the caller reads the result", "evidence": "line 2"}
HIGH = {"severity": "high", "file": "src/app.py", "line": 2, "claim": "sudo leaks records",
        "scenario": "a portal user calls answer", "evidence": "line 2"}
PASS = {"verdict": "pass", "findings": [LOW]}
CLAIMS_PASS_HOLDS_HIGH = {"verdict": "pass", "findings": [HIGH]}
WITHDRAWN = {"answers": [{"finding": 1, "answer": "withdrawn", "why": "the record rule filters them"}]}
REVIEW_MD = ".dev-ai/tasks/fix-answer/review.md"
MODEL = "gpt-6-sol"  # named on every review: a harness's default may be a free model (the owner, 2026-09-29)


def reviewable_task(repo: Path, author: str = "claude", spec: str | None = None) -> Path:
    task = commands.start(repo, "fix-answer", "make the answer right", ["src/app.py"], None, author, spec,
                          delivery="merge", author_model="claude-opus-5")  # said here, as the operator says it
    worktree = Path(task.worktree)
    (worktree / "src" / "app.py").write_text("def answer(env):\n    return env.sudo()\n", encoding="utf-8")
    assert commands.check(worktree, "fix-answer")["needs_review"] == ["src/app.py"]
    return worktree


def reviewer_says(monkeypatch: pytest.MonkeyPatch, answer: Any, returncode: int = 0, stderr: str = ""
                  ) -> list[tuple[list[str], str]]:
    """Replace the one process call that reaches a model."""
    calls: list[tuple[list[str], str]] = []

    def spawn(argv: list[str], brief: str, cwd: Path, timeout_s: int) -> subprocess.CompletedProcess[str]:
        calls.append((argv, brief))
        if isinstance(answer, Exception):
            raise answer
        text = answer if isinstance(answer, str) else json.dumps(answer)
        return subprocess.CompletedProcess(argv, returncode, stdout=text, stderr=stderr)

    monkeypatch.setattr(review, "_spawn", spawn)
    monkeypatch.setattr(review.shutil, "which", lambda name: f"/usr/bin/{name}")  # every reviewer's CLI on PATH
    return calls


def ask(worktree: Path, reviewer: str | None = None, model: str = MODEL, **named: Any) -> dict[str, Any]:
    """A review as the skill asks for one: its model named."""
    return review.run(worktree, "fix-answer", reviewer, model, **named)


def land(worktree: Path) -> dict[str, Any]:
    return commands.land(worktree, "fix-answer", "fix: x", merge=False)


def test_the_reviewer_runs_on_the_harness_login_never_on_an_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Task 021, 2026-09-21: `ANTHROPIC_API_KEY` sat in the environment, `claude` let it overrule the claude.ai
    login, the key was at its usage limit, and both claude reviews were unavailable in six seconds. The owner:
    "not the API key, the session". A fake command stands for the CLI; the rest of the environment stays."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder-for-the-test")
    monkeypatch.setenv("SOME_OTHER_VARIABLE", "kept")
    (fake := tmp_path / "opencode").write_text(  # its version only to a probe run under the review's env
        '#!/bin/sh\n[ "$1" = -v ] && exec echo "${OPENCODE_CONFIG_CONTENT:+$IS}"\necho "$@"; env\n')
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=":")  # 2.x: no --dir nor --variant, its directory from PWD
    for version, tail in (("1.18.31", f"--dir {tmp_path} -m m --variant high"), ("v2.2.6", "--standalone -m m#high")):
        monkeypatch.setenv("IS", version)
        seen = review._spawn(review._argv("opencode", tmp_path, tmp_path, "m", "high"), "", tmp_path, 9).stdout
        assert seen.startswith(f"run --agent plan {tail}\n") and f"\nPWD={tmp_path}\n" in seen
    assert "ANTHROPIC_API_KEY" not in seen and "SOME_OTHER_VARIABLE=kept" in seen
    # opencode has no read-only flag: its config, read after the project's, denies what writes or reaches out
    config = json.loads(next(line for line in seen.splitlines() if line.startswith("OPENCODE_CONFIG_CONTENT="))[24:])
    allowed = {tool for tool, rule in config["permission"].items() if rule != "deny"}
    assert list(config["permission"])[0] == "*" and allowed == {"read", "grep", "glob", "list"}  # MCP tools denied
    assert config["permission"]["read"]["*.env"] == "deny"  # opencode asks for these by default: never read here
    assert config["agent"]["plan"]["permission"] == config["permission"]  # a project's grant to the plan agent loses


def test_the_codex_reviewer_runs_with_each_mcp_server_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An operations repository, 2026-10-27: codex's reviewer ran context-mode's ctx_execute, which sourced
    the patched script outside codex's read-only sandbox. A fake `codex` stands for the real one."""
    fake = tmp_path / "codex"
    fake.write_text('#!/bin/sh\n[ "$*" = "--disable plugins --disable apps mcp list --json" ] && { [ "$LISTED" = slow '
                    '] && exec sleep 9; [ "$LISTED" != fail ] && echo "$LISTED"; exit; }\necho "$@" | tee ran\n',
                    encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=":")
    for listed in ("fail", "not json", "{}", '""', "null", "[{}]"):  # servers unknown: unavailable, codex never runs
        monkeypatch.setenv("LISTED", listed)
        argv = review._argv("codex", tmp_path, tmp_path / "answer", MODEL, "high")
        assert review._ask(argv, "", tmp_path, 9)[2] == "`codex` could not be started"
        assert not (tmp_path / "ran").exists()
    monkeypatch.setenv("LISTED", "slow")  # the listing is bounded by review_timeout too
    assert review._ask(argv, "", tmp_path, 1)[2] == "`codex` timed out after 1s (review_timeout)"
    monkeypatch.setenv("LISTED", '[{"name": "context-mode"}, {"name": "odoo"}]')
    ran = review._spawn(review._argv("codex", tmp_path, tmp_path / "answer", MODEL, "high"), "", tmp_path, 9).stdout
    assert ran.startswith("exec -c mcp_servers.context-mode.enabled=false -c mcp_servers.odoo.enabled=false --sandbox")
    assert "--disable plugins --disable apps" in ran


@pytest.mark.parametrize(("author", "reviewer", "read_only"),
    [("claude", "codex", "read-only"), ("codex", "claude", "plan"), ("human", "codex", "read-only")])
def test_the_other_harness_reviews_the_checked_patch_read_only(
    repo: Path, monkeypatch: pytest.MonkeyPatch, author: str, reviewer: str, read_only: str) -> None:
    worktree = reviewable_task(repo, author)
    calls = reviewer_says(monkeypatch, PASS)
    result = ask(worktree)
    checked = json.loads((repo / ".dev-ai/tasks/fix-answer/check.json").read_text(encoding="utf-8"))
    assert result["verdict"] == "pass" and result["reviewer"] == reviewer and result["requested_model"] == MODEL
    assert result["patch_sha256"] == checked["patch_sha256"]  # the review names the exact patch it read
    argv, brief = calls[0]
    assert argv[0] == reviewer and read_only in argv and MODEL in argv
    assert not any("danger" in arg or "bypass" in arg.lower() or "yolo" in arg for arg in argv)
    no_mcp = {"codex": "--disable plugins --disable apps", "claude": "--strict-mcp-config"}[reviewer]
    assert no_mcp in " ".join(argv) and "--mcp-config" not in argv  # MCP servers act outside the sandbox
    marks =[brief.index(mark) for mark in ("make the answer right", "SCOPE", "NEEDS THE REVIEW", "scenario",
                                            "env.sudo()")]
    assert marks == sorted(marks)  # goal, scope, what needs the review, questions, then the patch
    assert "name it" in (repo / REVIEW_MD).read_text(encoding="utf-8")


def test_with_no_other_harness_on_path_the_authors_own_reviews_with_another_model(
    repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A machine with Claude Code alone: codex is not on PATH, so claude reviews, under a model not the author's."""
    worktree = reviewable_task(repo)
    calls = reviewer_says(monkeypatch, PASS)
    monkeypatch.setattr(review.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None)
    assert ask(worktree)["reviewer"] == "claude" and calls[0][0][0] == "claude"


def test_the_reviewer_judges_against_the_short_spec_recorded_at_start(
    repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """On the bench the serious catches were breaches of declared invariants, and that contract
    also cost hours per task: so a spec is optional, short, and fixed when the task opens."""
    spec = repo.parent / "spec.md"
    spec.write_text("INV-1: only its owner reads a record\n" * 81, encoding="utf-8")
    with pytest.raises(TaskError, match="80 at most") as too_long:
        reviewable_task(repo, spec=str(spec))
    assert too_long.value.kind == "bad_spec" and not (repo / ".dev-ai/tasks/fix-answer").exists()
    with pytest.raises(TaskError, match="cannot read") as missing:
        reviewable_task(repo, spec=str(repo.parent / "absent.md"))
    assert missing.value.kind == "bad_spec" and not (repo / ".dev-ai/worktrees").exists()
    spec.write_text("INV-1: only its owner reads a record\n", encoding="utf-8")
    worktree = reviewable_task(repo, spec=str(spec))
    spec.write_text("INV-1: anybody reads anything\n", encoding="utf-8")  # later edits change nothing
    calls = reviewer_says(monkeypatch, PASS)
    ask(worktree)
    brief = calls[0][1]
    marks = [brief.index(mark) for mark in ("make the answer right", "only its owner reads", "SCOPE")]
    assert marks == sorted(marks) and "anybody reads anything" not in brief


def test_a_task_without_a_spec_gets_a_brief_without_one_but_with_its_dated_decisions(
        repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """2026-11-06: decisions made after `start` never reached the reviewer (576 grave findings refuted, 170 held)"""
    worktree = reviewable_task(repo)
    commands.scope_add(repo, "fix-answer", [], "the lead: option c, the rounding stays")
    calls = reviewer_says(monkeypatch, PASS)
    ask(worktree)
    assert "WHAT WAS DECIDED" not in calls[0][1] and "- decided on 20" in calls[0][1]
    assert "option c, the rounding stays" in calls[0][1].split("SCOPE")[1]
    assert commands.status(repo)[0]["review"] == "pass"
    commands.scope_add(repo, "fix-answer", [], "the owner: no rounding at all")  # the same second as the review
    assert commands.status(repo)[0]["review"] != "pass"  # a decision it never read (codex): reviewed again
    reviewer_says(monkeypatch, {"verdict": "fail", "findings": [HIGH]})
    assert ask(worktree)["verdict"] == "pending"
    commands.scope_add(repo, "fix-answer", [], "the lead: sudo stays")
    with pytest.raises(TaskError, match="already has a review") as kept:  # nor does a decision erase a finding
        ask(worktree)
    assert kept.value.kind == "review_pending"
    review.resolve(worktree, "fix-answer", 1, "refuted", "the lead decided sudo stays")
    reviewer_says(monkeypatch, WITHDRAWN)
    assert ask(worktree)["verdict"] == "pass"  # a re-examination answers its findings, it judges no new decision:
    assert commands.status(repo)[0]["review"] != "pass"  # its pass is stale (codex), and a full review follows
    calls = reviewer_says(monkeypatch, PASS)
    assert ask(worktree)["verdict"] == "pass" and "sudo stays" in calls[0][1]
    assert commands.status(repo)[0]["review"] == "pass"
    commands.scope_add(repo, "fix-answer", [], "the owner: env.sudo() is forbidden")
    reviewer_says(monkeypatch, {"verdict": "fail", "findings": [HIGH]})
    ask(worktree)
    review.resolve(worktree, "fix-answer", 1, "confirmed", "sudo is forbidden")
    commands.scope_add(repo, "fix-answer", [], "the lead: sudo is allowed here after all")
    with pytest.raises(TaskError) as failed:  # a confirmed finding stands until the patch changes (the owner, 11-06)
        ask(worktree)
    assert failed.value.kind == "review_failed"


def test_an_untracked_binary_reaches_the_reviewer_by_name_and_size_never_decoded(
    repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Task 229, 2026-10-04: 64 untracked screenshots, 5.1 MB decoded into the brief, which codex and
    claude both refused; the review stayed unavailable and land refused the task. Binary is git's rule: a NUL
    among the first 8 000 bytes, where a PNG's header puts one."""
    task = commands.start(repo, "fix-answer", "make the answer right", ["src/"], None, "claude",
                          author_model="claude-opus-5")
    worktree = Path(task.worktree)
    (worktree / "src" / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR" + bytes(2000))
    (worktree / "src" / "late.txt").write_bytes(b"a" * 8000 + b"\0")  # its NUL past git's 8 000 bytes: text
    calls = reviewer_says(monkeypatch, PASS)
    ask(worktree)
    brief = calls[0][1]
    assert "--- new untracked file: src/shot.png\n(binary file, 2016 bytes)" in brief and "IHDR" not in brief
    assert "--- new untracked file: src/late.txt\naaa" in brief


def test_a_review_names_its_model_and_opencode_reviews_read_only(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The bench, the 405 review runs read on 2026-09-29: codex raised a blocking finding in 67 % of its runs,
    claude reading claude in 17 %, opencode on its default free model in 11 %, and that model passed task-072
    and task-089 with no finding. The owner: a model is named on every review. On 2026-10-27 he took opencode
    back as a harness like the others, its model named too."""
    worktree = reviewable_task(repo)
    calls = reviewer_says(monkeypatch, PASS)
    for unnamed in ({}, {"reviewer": "codex"}):
        with pytest.raises(TaskError, match="with which model") as refused:
            review.run(worktree, "fix-answer", **{"reviewer": None} | unnamed)
        assert refused.value.kind == "no_model" and "--model" in str(refused.value)
    assert calls == [] and not (repo / ".dev-ai/tasks/fix-answer/review.json").exists()  # no model was called
    assert cli.main(["review", "--reviewer", "opencode", "--model", "openai/gpt-6-sol"], cwd=worktree) == 0
    argv = calls[0][0]  # the plan agent, asks refused without --auto, the brief on stdin, the answer on stdout
    assert argv[:4] == ["opencode", "run", "--agent", "plan"] and argv[argv.index("--dir") + 1] == str(worktree)
    assert argv[-4:] == ["-m", "openai/gpt-6-sol", "--variant", "high"] and "--auto" not in argv
    assert json.loads((repo / ".dev-ai/tasks/fix-answer/review.json").read_text(encoding="utf-8"))["verdict"] == "pass"


def test_a_review_recorded_before_models_were_named_still_stands(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The evidence is bound to the patch, not to the rule of the day: a task in flight, passed by a
    reviewer nobody named a model for, lands as it would have."""
    worktree = reviewable_task(repo)
    reviewer_says(monkeypatch, PASS)
    ask(worktree)
    record = repo / ".dev-ai/tasks/fix-answer/review.json"
    before = {**json.loads(record.read_text(encoding="utf-8")), "reviewer": "opencode", "requested_model": ""}
    record.write_text(json.dumps(before), encoding="utf-8")
    assert land(worktree)["review"] == "pass"


def test_a_blocking_finding_is_pending_until_evidence_confirms_or_refutes_it(
    repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The reviewer's severity is a claim. A run of the same patch never erases an open one."""
    worktree = reviewable_task(repo)
    reviewer_says(monkeypatch, CLAIMS_PASS_HOLDS_HIGH)
    pending = ask(worktree)
    assert pending["verdict"] == "pending" and pending["findings"][0]["resolution"] == "pending"
    with pytest.raises(TaskError, match="await evidence") as unresolved:
        ask(worktree)
    assert unresolved.value.kind == "review_pending"
    with pytest.raises(TaskError, match="from 1 to 1") as bad:
        review.resolve(worktree, "fix-answer", 2, "refuted", "no such finding")
    assert bad.value.kind == "bad_resolution"
    with pytest.raises(TaskError, match="without evidence"):
        review.resolve(worktree, "fix-answer", 1, "refuted", "  ")
    refuted = review.resolve(worktree, "fix-answer", 1, "refuted", "the ORM rule filters portal records")
    assert refuted["verdict"] == "pending" and refuted["findings"][0]["resolution"] == "refuted"  # the reviewer's turn
    assert refuted["findings"][0]["resolution_evidence"].startswith("the ORM")
    assert "await the reviewer" in refuted["reason"]
    assert "REFUTED" in (repo / REVIEW_MD).read_text(encoding="utf-8")


def test_a_confirmed_blocker_fails_the_patch_and_resolving_needs_the_current_patch(
    repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    worktree = reviewable_task(repo)
    reviewer_says(monkeypatch, CLAIMS_PASS_HOLDS_HIGH)
    ask(worktree)
    with pytest.raises(TaskError, match="await evidence") as open_finding:
        land(worktree)
    assert open_finding.value.kind == "review_pending"
    failed = review.resolve(worktree, "fix-answer", 1, "confirmed", "reproduced with a portal user")
    assert failed["verdict"] == "fail" and "CONFIRMED" in (repo / REVIEW_MD).read_text(encoding="utf-8")
    with pytest.raises(TaskError, match="review failed this patch") as refused:
        land(worktree)
    assert refused.value.kind == "review_failed"
    reviewer_says(monkeypatch, PASS)
    with pytest.raises(TaskError, match="already has a failed review") as rerolled:  # no reroll into a pass
        ask(worktree, "claude", "claude-sonnet-5")
    assert rerolled.value.kind == "review_failed" and "CONFIRMED" in (repo / REVIEW_MD).read_text(encoding="utf-8")
    (worktree / "src/app.py").write_text("def answer(env):\n    return env.ids\n", encoding="utf-8")
    with pytest.raises(TaskError, match="no review of the current patch") as none:
        review.resolve(worktree, "fix-answer", 1, "refuted", "another patch")
    assert none.value.kind == "review_missing"


@pytest.mark.parametrize(("answer", "returncode"), [
        ("It looks fine to me.", 0),
        (PASS, 1),  # a provider error with a plausible answer is still no review
        ({"verdict": "pass"}, 0),
        ({"verdict": "pass", "findings": 3}, 0),  # not iterable: read, never crashed on
        ({"verdict": "pass", "findings": [{"severity": "urgent"}]}, 0),
        ({"verdict": "fail", "findings": []}, 0),  # a fail that names nothing is no answer, and was read as pass
        ({"is_error": True, "error": "quota"}, 0),  # a provider error that exits 0
        (subprocess.TimeoutExpired("codex", 900, output="partial", stderr="slow"), 0),
        (FileNotFoundError("codex"), 0),
    ],
)
def test_anything_but_a_well_formed_answer_is_unavailable_never_pass(
    repo: Path, monkeypatch: pytest.MonkeyPatch, answer: Any, returncode: int) -> None:
    """The bench TASK-068: a reviewer died on `provider_error` and its wrapper threw stderr
    away, so nobody could say why. The whole output is kept and the blocker names it."""
    worktree = reviewable_task(repo)
    reviewer_says(monkeypatch, answer, returncode, stderr="provider_error: quota")
    result = ask(worktree)
    assert result["verdict"] == "unavailable" and result["log"] in result["reason"]
    kept = Path(result["log"]).read_text(encoding="utf-8")
    assert Path(result["log"]).name == "review.log" and "codex exec" in kept
    assert isinstance(answer, Exception) or "provider_error: quota" in kept


def test_a_retry_keeps_the_run_it_retries_in_the_log(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The bench, evals-oracle-068: the retry this tool advises overwrote the failing output, so the
    run that read `unavailable` could no longer be explained. Every run is appended."""
    worktree = reviewable_task(repo)
    reviewer_says(monkeypatch, "no json here", stderr="provider_error: quota")
    assert ask(worktree)["verdict"] == "unavailable"
    reviewer_says(monkeypatch, PASS)
    second = ask(worktree)
    kept = Path(second["log"]).read_text(encoding="utf-8")
    assert second["verdict"] == "pass" and kept.count("--- stdout") == 2
    assert "no json here" in kept and "provider_error: quota" in kept  # the failure stays explicable


def test_an_unavailable_review_names_every_way_out_that_is_left(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A blocker says how to recover. With codex out, what is left is this harness with a model
    other than the author's; the message has to say so, or nobody knows."""
    worktree = reviewable_task(repo)
    task_path = repo / ".dev-ai/tasks/fix-answer/task.json"
    task = json.loads(task_path.read_text(encoding="utf-8"))
    reviewer_says(monkeypatch, {"is_error": True, "error": "quota"})
    task_path.write_text(json.dumps({**task, "author_model": ""}), encoding="utf-8")  # opened before it was required
    stuck = ask(worktree, "codex")
    assert stuck["verdict"] == "unavailable" and "--reviewer claude" not in stuck["reason"]  # no model to differ
    assert "--reviewer opencode --model <id>" in stuck["reason"]  # the third harness is left
    task_path.write_text(json.dumps({**task, "author": "human", "author_model": ""}), encoding="utf-8")
    assert "--reviewer claude --model <id>" in ask(worktree, "codex")["reason"]  # another harness, its model named
    task_path.write_text(json.dumps({**task, "author_model": "claude-opus-5"}), encoding="utf-8")
    assert "--reviewer claude --model <not claude-opus-5>" in ask(worktree, "codex")["reason"]


def test_a_reviewer_that_explains_itself_before_answering_is_still_a_review(
    repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The bench, evals-oracle-068: claude answered `pass` after a paragraph and inside a fence, the
    run read `unavailable`, and the retry cost a second round-trip. An object carrying a verdict is
    an answer wherever it sits; among several, the most blocking one, then the last of equals."""
    worktree = reviewable_task(repo)
    reviewer_says(
        monkeypatch,
        'Only the docstring mentions it, and `{"invalid_fields": 1}` is gone from the code.\n\n'
        '```json\n{"verdict": "pass", "findings": []}\n```\n',
    )
    assert ask(worktree)["verdict"] == "pass"


def test_the_last_of_equally_blocking_answers_is_the_one_that_counts(
    repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither object blocks, so neither is stricter: the review is the one the reviewer ended on."""
    worktree = reviewable_task(repo)
    reviewer_says(
        monkeypatch,
        '{"verdict": "pass", "findings": []}\n\nOn a closer look: ' + json.dumps({"verdict": "pass",
                                                                                 "findings": [LOW]}),
    )
    assert [finding["claim"] for finding in ask(worktree)["findings"]] == ["name it"]


@pytest.mark.parametrize("benign_first", [True, False])
def test_a_second_answer_in_the_output_never_softens_the_one_that_blocks(
    repo: Path, monkeypatch: pytest.MonkeyPatch, benign_first: bool) -> None:
    """Neither an example before the answer nor a remark after it may hide a blocking finding, whichever way
    round they fall: scanning the output may only ever move the verdict towards `fail`."""
    worktree = reviewable_task(repo)
    benign, blocking = json.dumps({"verdict": "pass", "findings": []}), json.dumps(
        {"verdict": "pass", "findings": [HIGH]}  # the reviewer's own word is not the contract
    )
    parts = [benign, blocking] if benign_first else [blocking, benign]
    reviewer_says(monkeypatch, f"For instance {parts[0]}\n\nOn reflection: {parts[1]}\n")
    result = ask(worktree)
    assert result["verdict"] == "pending" and [finding["claim"] for finding in result["findings"]] == [HIGH["claim"]]


def test_a_review_needs_no_check_and_a_landing_needs_both_of_the_same_patch(
    repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The bench since 0.13.0, the median task: a check of 9.8 min, then a review of 3 (2026-09-29). The review reads
    the patch as it stands, beside the check, and refuses before any model what the check refuses before its tests."""
    task = commands.start(repo, "fix-answer", "make the answer right", ["src/app.py"], None, "claude",
                          delivery="merge", author_model="claude-opus-5")
    worktree = Path(task.worktree)
    calls = reviewer_says(monkeypatch, PASS)
    with pytest.raises(TaskError, match="patch is empty") as empty:
        ask(worktree)
    (worktree / "src" / "extra.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(TaskError, match="outside the task scope") as stray:
        ask(worktree)
    assert (empty.value.kind, stray.value.kind, calls) == ("empty_patch", "out_of_scope", [])
    (worktree / "src" / "extra.py").unlink()
    (worktree / "src" / "app.py").write_text("def answer(env):\n    return env.sudo()\n", encoding="utf-8")
    assert ask(worktree)["verdict"] == "pass" and len(calls) == 1  # no check has run
    row = commands.status(repo)[0]  # codex, on this patch: status read that review stale until a check passed
    assert (row["check"], row["review"], row["next"]) == ("-", "pass", "check")
    with pytest.raises(TaskError, match="no passing check") as unchecked:
        land(worktree)
    assert unchecked.value.kind == "unchecked"
    commands.check(worktree, "fix-answer")
    assert land(worktree)["review"] == "pass" and len(calls) == 1  # the review of that patch stands


def test_landing_prints_the_evidence_it_relies_on(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    worktree = reviewable_task(repo)
    reviewer_says(monkeypatch, PASS)
    ask(worktree)
    capsys.readouterr()
    record = land(worktree)
    assert record["needs_review"] == ["src/app.py"] and record["review"] == "pass"
    shown = capsys.readouterr().out  # plain text from the records, no model
    for part in ("src/app.py", "exit 0", "pass by codex", "1 low", "review.md", "fix: x"):
        assert part in shown


def test_landing_and_status_name_the_reviewer_and_the_model_asked_for(
    repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The twenty-task routine of 2026-09-28 had to parse review.log to know who had read each patch."""
    worktree = reviewable_task(repo)
    reviewer_says(monkeypatch, PASS)
    ask(worktree)
    assert commands.status(repo)[0]["reviewer"] == f"codex:{MODEL}"
    record = land(worktree)
    assert (record["reviewer"], record["requested_model"]) == ("codex", MODEL)
    path = repo / ".dev-ai/tasks/fix-answer/review.json"
    named = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({key: value for key, value in named.items() if key != "reviewer"}), encoding="utf-8")
    assert commands.status(repo)[0]["reviewer"] == f"?:{MODEL}"  # status reads a record loosely, and lands nothing


def test_a_patch_that_changes_behaviour_lands_only_with_a_passing_review_of_this_exact_patch(
    repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    worktree = reviewable_task(repo)
    with pytest.raises(TaskError, match="dev-ai review") as missing:
        land(worktree)
    assert missing.value.kind == "review_missing"
    reviewer_says(monkeypatch, PASS)
    ask(worktree)
    (worktree / "src" / "app.py").write_text("def answer(env):\n    return env.sudo().ids\n", encoding="utf-8")
    commands.check(worktree, "fix-answer")  # another patch: the recorded review says nothing about it
    with pytest.raises(TaskError, match="dev-ai review") as stale:
        land(worktree)
    assert stale.value.kind == "review_missing"
    ask(worktree)
    assert land(worktree)["review"] == "pass"


def test_the_reviewer_reads_the_patch_that_was_scanned_and_recorded(
    repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Codex: a test run wrote to the patch between the scan and the brief, and a pass was recorded for bytes never
    read. The fingerprint is taken again before the brief goes out, and after the answer, or nothing stands."""
    worktree = reviewable_task(repo)
    app, brief = worktree / "src" / "app.py", review._brief

    def written(*args: Any) -> str:
        text = brief(*args)
        app.write_text(app.read_text(encoding="utf-8") + "# a test wrote here\n", encoding="utf-8")
        return text

    monkeypatch.setattr(review, "_brief", written)
    calls = reviewer_says(monkeypatch, PASS)
    with pytest.raises(TaskError, match="nothing was sent") as moved:
        ask(worktree)
    assert moved.value.kind == "patch_moved" and calls == []
    monkeypatch.setattr(review, "_brief", brief)

    def spawn(argv: list[str], text: str, cwd: Path, timeout_s: int) -> subprocess.CompletedProcess[str]:
        app.write_text(app.read_text(encoding="utf-8") + "# and while it read\n", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(PASS), stderr="")

    monkeypatch.setattr(review, "_spawn", spawn)
    result = ask(worktree)
    assert result["verdict"] == "unavailable" and "changed while it was reviewed" in result["reason"]


def test_a_review_stands_on_a_moved_base_while_the_files_it_read_are_the_same(
    repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """settings-all-counted, 2026-09-29: two merges into main touched none of its files and the same diff was read
    again. The review stands while the base leaves the patch's files as they were, and goes when it moved them."""
    worktree = reviewable_task(repo)
    calls = reviewer_says(monkeypatch, PASS)
    read = ask(worktree)
    sh(worktree, "git", "commit", "-qam", "the patch")
    (repo / "src" / "legacy.py").write_text("password = load_secret()\nlater = True\n", encoding="utf-8")
    sh(repo, "git", "commit", "-qam", "main moved on, beside the patch")
    sh(worktree, "git", "merge", "-q", "--no-edit", "main")
    assert commands.check(worktree, "fix-answer")["base_sha"] != read["base_sha"]
    assert commands.status(repo)[0]["review"] == "pass" and len(calls) == 1
    (repo / "src" / "app.py").write_text("def answer():\n    return 43\n", encoding="utf-8")
    sh(repo, "git", "commit", "-qam", "main moved on, under the patch")
    sh(worktree, "git", "merge", "-q", "--no-edit", "-X", "ours", "main")  # main's line undone, and no byte moved
    assert commands.check(worktree, "fix-answer")["patch_sha256"] == read["patch_sha256"]
    with pytest.raises(TaskError, match="dev-ai review") as unread:
        land(worktree)
    assert unread.value.kind == "review_missing" and len(calls) == 1
    ask(worktree)
    assert land(worktree)["review"] == "pass" and len(calls) == 2


def test_an_unavailable_review_blocks_and_a_retry_with_the_other_reviewer_unblocks(
    repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No fallback chain and no ledger: the operator re-runs the command, as often as needed."""
    worktree = reviewable_task(repo)
    reviewer_says(monkeypatch, "garbage")
    ask(worktree)
    with pytest.raises(TaskError, match="--reviewer claude --model <not claude-opus-5>") as blocked:
        land(worktree)  # the author's harness, with another model
    assert blocked.value.kind == "review_unavailable"
    calls = reviewer_says(monkeypatch, PASS)
    assert ask(worktree, "claude", "claude-sonnet-5")["verdict"] == "pass" and calls[0][0][0] == "claude"
    assert land(worktree)["review"] == "pass"


def test_the_reviewer_is_another_harness_and_never_a_model_known_to_be_the_authors(
    repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TASK-063: claude reviewed claude's patch; 926e433: `openai/gpt-5.6-sol` passed against an author recorded as
    `gpt-5.6-sol`. The author's harness may review with another model, named; with none recorded, it is refused."""
    worktree = reviewable_task(repo)
    calls = reviewer_says(monkeypatch, PASS)
    task_path = repo / ".dev-ai/tasks/fix-answer/task.json"
    task = json.loads(task_path.read_text(encoding="utf-8"))
    task_path.write_text(json.dumps({**task, "author_model": ""}), encoding="utf-8")  # opened before it was required
    with pytest.raises(TaskError, match="another harness") as same_harness:
        ask(worktree, "claude", "claude-sonnet-5")
    assert same_harness.value.kind == "same_reviewer"
    task_path.write_text(json.dumps({**task, "author_model": "gpt-5.6-sol"}), encoding="utf-8")
    with pytest.raises(TaskError, match="own model") as same_model:
        ask(worktree, "codex", "gpt-5.6-sol")
    assert same_model.value.kind == "same_reviewer" and calls == []
    with pytest.raises(TaskError, match="own model") as prefixed:  # 926e433: provider/model slipped past
        ask(worktree, "codex", "openai/gpt-5.6-sol")
    assert prefixed.value.kind == "same_reviewer" and calls == []
    result = ask(worktree, "codex", "gpt-6-astra")
    assert calls[0][0][calls[0][0].index("-m") + 1] == "gpt-6-astra" and calls[0][0][-1] == "-"
    # the effort is asked too, high unless named: codex's own config said low (the owner, 2026-10-02)
    assert calls[0][0][calls[0][0].index("-c") + 1] == 'model_reasoning_effort="high"'
    assert result["requested_model"] == "gpt-6-astra" and result["observed_model"] == ""
    assert result["requested_effort"] == "high"
    assert "effort `high`, observed unknown" in (repo / REVIEW_MD).read_text(encoding="utf-8")
    with pytest.raises(TaskError, match="own model"):  # the author's harness, the author's model
        ask(worktree, "claude", "gpt-5.6-sol")
    own = ask(worktree, "claude", "claude-sonnet-5", effort="max")  # the owner's rule of 2026-09-20
    assert own["verdict"] == "pass" and own["reviewer"] == "claude" and own["requested_model"] == "claude-sonnet-5"
    assert calls[-1][0][:2] == ["claude", "-p"]
    assert calls[-1][0][-4:] == ["--model", "claude-sonnet-5", "--effort", "max"]


def test_a_review_recorded_before_findings_carried_evidence_is_not_current_proof(repo: Path) -> None:
    directory = repo / ".dev-ai/tasks/fix-answer"
    directory.mkdir(parents=True)
    (directory / "review.json").write_text(json.dumps({"patch_sha256": "abc", "verdict": "pass"}), encoding="utf-8")
    assert review.standing(repo, "fix-answer", {"patch_sha256": "abc"}) == {}


def test_cli_review_exits_by_verdict_resolves_by_number_and_logs_it(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    worktree = reviewable_task(repo)
    assert cli.main(["land", "-m", "fix: x"], cwd=worktree) == 1
    calls = reviewer_says(monkeypatch, CLAIMS_PASS_HOLDS_HIGH)
    assert cli.main(["review", "--model", MODEL], cwd=worktree) == 1
    assert 'model_reasoning_effort="high"' in calls[0][0]  # --effort omitted: high, never the CLI's own default
    assert "1. HIGH pending" in capsys.readouterr().out
    assert cli.main(["review", "--resolve", "1", "--resolution", "refuted", "--evidence", "ir.rule"], cwd=worktree) == 1
    assert cli.main(["land", "-m", "fix: x"], cwd=worktree) == 1  # refuted by the author alone: the reviewer's turn
    reviewer_says(monkeypatch, WITHDRAWN)
    assert cli.main(["review", "--model", MODEL], cwd=worktree) == 0
    assert cli.main(["land", "-m", "fix: x"], cwd=worktree) == 0
    rows = [json.loads(line) for line in (repo / ".dev-ai/log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(row["command"], row["outcome"], row.get("verdict"), row.get("reviewer")) for row in rows] == [
        ("land", "blocked", None, None), ("review", "blocked", "pending", "codex"),
        ("review", "blocked", "pending", "codex"), ("land", "blocked", None, None),
        ("review", "ok", "pass", "codex"), ("land", "ok", None, None),
    ]
    assert rows[3]["kind"] == "review_pending" and "approved" not in rows[5] and rows[5]["merged"] is False
    # findings by severity, so that what reviews catch over time is read from the log alone
    assert rows[1]["findings"] == {"critical": 0, "high": 1, "medium": 0, "low": 0}
    # a blocked row still names its task, found from the worktree: timings are read per task
    assert rows[0]["kind"] == "review_missing" and {row["task"] for row in rows} == {"fix-answer"}
    assert rows[1]["kind"] == rows[2]["kind"] == "review_pending" and "kind" not in rows[4]  # counted by kind
    assert cli.main(["status"], cwd=repo) == 0 and f"by=codex:{MODEL}" in capsys.readouterr().out


def test_a_review_that_blocks_logs_its_kind_and_its_reviewer(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    worktree = reviewable_task(repo)

    def spawn(argv: list[str], brief: str, cwd: Path, timeout_s: int) -> subprocess.CompletedProcess[str]:
        answer = "quota" if argv[0] == "codex" else json.dumps(CLAIMS_PASS_HOLDS_HIGH)
        return subprocess.CompletedProcess(argv, 0, stdout=answer, stderr="")

    monkeypatch.setattr(review, "_spawn", spawn)
    assert cli.main(["review", "--model", MODEL], cwd=worktree) == 1
    assert cli.main(["review", "--reviewer", "claude", "--model", "claude-sonnet-5"], cwd=worktree) == 1
    assert cli.main(["review", "--resolve", "1", "--resolution", "confirmed", "--evidence", "seen"], cwd=worktree) == 1
    rows = [json.loads(line) for line in (repo / ".dev-ai/log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(row["kind"], row["reviewer"], row["model"]) for row in rows] == [
        ("review_unavailable", "codex", MODEL), ("review_pending", "claude", "claude-sonnet-5"),
        ("review_failed", "claude", "claude-sonnet-5"),  # the run again, with the other harness: no fallback to name
    ]


def test_a_review_of_a_merged_task_blocks_and_says_so(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Task 034, merged: a review asked of it exited 2 on git's own `cannot change to`, its worktree being gone."""
    worktree = reviewable_task(repo)
    calls = reviewer_says(monkeypatch, PASS)
    ask(worktree)
    commands.land(repo, "fix-answer", "fix: the answer", merge=True)
    assert cli.main(["review", "--task", "fix-answer", "--model", MODEL], cwd=repo) == 1
    assert "is gone" in capsys.readouterr().err and len(calls) == 1  # a blocker, and no model called for it
    rows = [json.loads(line) for line in (repo / ".dev-ai/log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert (rows[-1]["outcome"], rows[-1]["kind"]) == ("blocked", "worktree_gone")


@pytest.mark.parametrize(("reviewer", "model"), [("codex", MODEL), ("claude", "claude-sonnet-5"),
                                                ("opencode", "openai/gpt-6-sol")])
def test_a_refuted_finding_goes_back_to_the_reviewer_never_to_the_operator(
    repo: Path, monkeypatch: pytest.MonkeyPatch, reviewer: str, model: str) -> None:
    """The owner, 2026-10-27: never ask him to approve blind. On the bench last-step-notice, records-ceiling-last-turn,
    joins-evidence-grader and canary-precheck-complete each landed on his word over a refuted finding, and the same
    defect came back as a Fixes-task. The reviewer reads the author's evidence; whatever harness, nobody types."""
    worktree = reviewable_task(repo)
    reviewer_says(monkeypatch, CLAIMS_PASS_HOLDS_HIGH)
    ask(worktree)
    review.resolve(worktree, "fix-answer", 1, "refuted", "the ORM rule filters portal records")
    with pytest.raises(TaskError, match="await the reviewer") as waiting:
        land(worktree)
    assert waiting.value.kind == "review_pending" and commands.status(repo)[0]["next"] == "review"  # not --resolve
    calls = reviewer_says(monkeypatch, WITHDRAWN)
    with pytest.raises(TaskError, match="own model"):  # the same independence as any review
        ask(worktree, "claude", "claude-opus-5")
    settled = ask(worktree, reviewer, model)
    assert len(calls) == 1 and calls[0][0][0] == reviewer  # one call, the patch and each refutation with its evidence
    assert all(text in calls[0][1] for text in ("sudo leaks records", "the ORM rule filters portal records",
                                                "withdrawn", "env.sudo()", CLAIMS_PASS_HOLDS_HIGH["findings"][0]
                                                ["evidence"]))  # its own evidence too (codex, on this patch)
    assert settled["verdict"] == "pass" and settled["findings"][0]["resolution"] == "withdrawn"
    record = commands.land(repo, "fix-answer", "fix: the answer", merge=True)
    assert record["merged"] is True and "approved" not in record


def test_a_maintained_finding_fails_the_patch_and_no_answer_leaves_it_open(
    repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    worktree = reviewable_task(repo)
    reviewer_says(monkeypatch, CLAIMS_PASS_HOLDS_HIGH)
    ask(worktree)
    review.resolve(worktree, "fix-answer", 1, "refuted", "the ORM rule filters portal records")
    for answer, returncode in (("not json", 0), ({"answers": []}, 0), (PASS, 0), (WITHDRAWN, 1),
                               ({"answers": [{"finding": 1, "answer": "perhaps"}]}, 0),
                               ({"answers": [{"finding": True, "answer": "withdrawn", "why": "x"}]}, 0),  # codex
                               ({"answers": [{"finding": 1, "answer": "withdrawn"}]}, 0)):  # withdrawn, saying why
        reviewer_says(monkeypatch, answer, returncode)
        stays = ask(worktree)  # never a pass by default
        assert stays["verdict"] == "pending" and stays["findings"][0]["resolution"] == "refuted"
        assert "stay open" in stays["reason"]
    reviewer_says(monkeypatch, {"answers": [{"finding": 1, "answer": "maintained", "why": "reproduced"}]})
    failed = ask(worktree)
    assert failed["verdict"] == "fail" and failed["findings"][0]["resolution"] == "confirmed"
    with pytest.raises(TaskError, match="its answer stands") as reroll:  # codex, on this patch: refuted again, re-asked
        review.resolve(worktree, "fix-answer", 1, "refuted", "still the ORM rule")
    assert reroll.value.kind == "bad_resolution"
    with pytest.raises(TaskError, match="review failed") as refused:
        land(worktree)
    assert refused.value.kind == "review_failed"


def test_a_review_passed_over_a_refutation_before_this_change_is_re_examined_and_a_new_patch_starts_afresh(
    repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    worktree = reviewable_task(repo)
    reviewer_says(monkeypatch, CLAIMS_PASS_HOLDS_HIGH)
    ask(worktree)
    review.resolve(worktree, "fix-answer", 1, "refuted", "the ORM rule filters portal records")
    path = repo / ".dev-ai/tasks/fix-answer/review.json"  # as the 0.x `resolve` left it: a pass over a refutation
    path.write_text(json.dumps({**json.loads(path.read_text(encoding="utf-8")), "verdict": "pass"}), encoding="utf-8")
    with pytest.raises(TaskError, match="await the reviewer"):
        land(worktree)
    assert commands.status(repo)[0]["next"] == "review"  # codex, on this patch: status said land
    reviewer_says(monkeypatch, "not json")
    assert ask(worktree)["verdict"] == "pending"  # codex, on this patch: a failed re-read kept the old pass
    assert commands.status(repo)[0]["next"] == "review"
    (worktree / "src" / "app.py").write_text("def answer(env):\n    return env\n", encoding="utf-8")
    commands.check(worktree, "fix-answer")
    calls = reviewer_says(monkeypatch, PASS)
    assert ask(worktree)["verdict"] == "pass" and "withdrawn" not in calls[0][1]  # nothing carried over
    assert land(worktree)["review"] == "pass"
