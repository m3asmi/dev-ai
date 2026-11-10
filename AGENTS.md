# AGENTS.md

Canonical instructions for AI-assisted work in this repository. `CLAUDE.md` is a
pointer to this file; edit only this one.

## What this is

`dev-ai` contains AI-assisted development and proves the patch — README's four
promises — and replaces dev-pipeline for one developer using frontier models.
Read `README.md` (use), `docs/design.md` (invariants), `docs/roadmap.md` (tracking
your use, what is not planned), `docs/howto.md` (one task, step by step).

## The rule that outranks the others: the budget

| Limit | Value | Enforced by |
|---|---|---|
| Code (`devai/`, `scripts/*.sh`) | ≤ 1 640 lines, `review.py` ≤ 260 | `tests/test_budget.py` |
| Tests (`tests/`) | ≤ 2 000 lines | `tests/test_budget.py` |
| Docs (`README.md`, `AGENTS.md`, `docs/*.md`) | ≤ 705 lines | `tests/test_budget.py` |
| Settings (config keys + env vars) | ≤ 11 | `tests/test_budget.py` |
| Suite duration | < 60 s | `tests/conftest.py` |
| Model calls outside `devai/review.py` | 0 | `tests/test_budget.py` |

Adding means removing. The limits no longer move (the owner moved them once more for
opencode, 2026-10-27): a need that does not fit removes something first, or waits.

**Stop criterion**: a limit exceeded twice, or more than one
fix commit to this tool per task delivered with it, and work here stops.

## Mistakes not to repeat

dev-pipeline's, the larger tool dev-ai replaced, measured on 2026-09-17.

| Mistake | Evidence | Here |
|---|---|---|
| Grew without a ceiling | 52 000 lines, 466 settings, 3 305 tests not done in 90 min | budget tests; adding means removing |
| An LLM orchestrated a 1 042-line contract | TASK-039 | deterministic code; a model only in `review.py` |
| Defended against a forger that never came | provenance caught 0 faults, blocked runs | fixed threat model |
| Every incident added a guard | 169 of 251 commits were fixes | no guard without a real failed case |
| Kept stages nobody measured | council 0 of 22, design gate 2 of 77 | every blocker has a kind, logged; unused checks go |
| Failed on its own paperwork | TASK-051, 046, 048, 056 | blockers are about the patch; bookkeeping fails open |
| Stopped the human too often | 31 + 42 stops | the harness's prompt and the mandate recorded at `start`; none of dev-ai's own: a refuted finding goes back to the reviewer |
| Fallback chains, retry budgets, ledger | a steady source of fixes | one reviewer, one attempt; every command re-runs |
| Tool edits live for every consumer | runners symlinked to the working checkout | run from a stable worktree at `main`'s tip (README) |
| Several sessions patched the tool | stray fix branches | one owning session; consumers report |
| The tool became the project | fix lots H to O | stop criterion; the product is what it serves |

## Rules

- **No LLM in orchestration.** Commands are deterministic code. No prompt-driven
  contract, no planner, no model catalogue in the tool, no runner adapters: the
  harness picks the model, and dev-ai passes the reviewer's `--model` on.
- **No new guard without a real failed case.** Name the task and what went wrong
  in the commit that adds the guard. Speculative checks are refused.
- **Every change pays for itself.** Its commit names the gain (a real failed case, fewer
  stops, a shorter start → land) and adds no step, stop or wait to that path; else it waits.
- **dev-ai complements the harness, never duplicates it** (the owner, 2026-10-15). Every change
  fills a gap the harness leaves or removes from dev-ai what the harness now does (permissions,
  sandbox, agents, model choice, memory); its commit names which. A rebuilt harness feature is refused.
- **Every blocker says what, why and how to recover**, in one message.
- **Standard library only.** No runtime dependency.
- **The threat model is fixed** (`docs/design.md`): the model is competent and
  fallible, not a forger. Do not add signed receipts, sealed inputs, attestation,
  immutable ledgers or retry budgets.
- Tests use throwaway git repositories and fake commands: no real Odoo, no real
  model, no network, and never the operator's own harness settings.
- `dev-ai` never pushes. Neither do you, without an explicit instruction. Same
  for commits, merges and anything irreversible.
- Never use `--dangerously-skip-permissions`, `yolo`, or a trust bypass, in code
  or in your own session.
- Do not read or write outside this repository during a task.

## Working here

```
python3 -m pytest            # whole suite, a few seconds
ruff check devai tests       # lint
git config core.hooksPath hooks   # once: run both before every commit
```

Test first when behaviour changes. Inspect the final diff, run `git diff --check`,
run the suite after the last edit. Commit format: `<type>: <description>` with
type in `feat|fix|refactor|docs|test|chore|perf|ci`.

## Working with dev-ai

This repository is migrated, and this section is the note itself: `dev-ai init` copies
its bullets into any repository that uses dev-ai. Here too a task is judged by the
installed dev-ai, never by this checkout, and `/dev-ai` (`docs/skill.md`) carries it.

- Open the task with `dev-ai start` (author, its model, delivery). Work only inside the worktree it printed.
- Touch only the task's scope. A file the goal needs joins it with `dev-ai scope-add <path> --reason "…"`.
- Run each `dev-ai` command bare, from the main checkout: behind `cd …&&`, `env`, a pipe,
  a redirect or `&`, your harness's rules no longer match it.
- Run `dev-ai check` before calling the work done. A suite can outlast your shell tool's
  time limit: run it in the background with your harness's own tool and read
  `.dev-ai/tasks/<task>/test.log` in the main checkout. Running it again is always safe.
- Unless the patch is descriptive documentation only, run `dev-ai review` beside the check,
  both in the background; confirm or refute each blocking finding with `dev-ai review --resolve`,
  with evidence; fix what is confirmed, then check and review again. A patch touching a
  secret-bearing file fails its check and its review: take it out.
- Check passed, review passed or not needed: `dev-ai land -m "…" --merge`, within the mandate. Never push.
- End with what you decided without being told: the reviewer is asked exactly that.

## Layout

```
bin/dev-ai          entry point (symlink it onto PATH); hooks/pre-commit: suite + lint
devai/cli.py        argparse, exit codes, one JSONL row per command
devai/commands.py   init, start, check, land, drop, scope-add, status, clean
devai/task.py       task state, mandate, configuration, scope matching, freshness of evidence
devai/gitops.py     bounded git calls, exact-patch fingerprint, untracked and ignored files
devai/impact.py     what needs a review (all but descriptive docs), the secret deny list
devai/testgate.py   host test run
devai/review.py     the one model call: another harness reviews the patch, beside its check; findings resolved
scripts/install.sh  installs main's tip and the skill, the one entry point; each harness's user rules
scripts/dev-ai.rules  codex's rules, copied to ~/.codex/rules/ by the installer
scripts/clean-worktrees.sh, drop-test-dbs.sh  what `dev-ai clean` runs, per project by arguments; dry run unless --yes
tests/              test_flow.py, test_review.py, test_install.py, test_cleanup.py (behaviour), test_budget.py
```
