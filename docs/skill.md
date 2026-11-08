---
name: dev-ai
description: Carry one task through dev-ai to the end in a migrated repository: open or resume it, work in its worktree, check, have another harness review the patch, resolve its findings with evidence, land within the mandate. Trigger with /dev-ai, or $dev-ai in codex.
---

# dev-ai task

This is the skill every harness reads; `scripts/install.sh` copies it into each
one. `dev-ai` contains the work and proves the patch; you drive it from the
repository's main checkout. Every command runs under your harness's own
permission rules, the operator's user settings for Claude Code and the rule `dev-ai init`
writes in that repository for codex, so the flow runs to the end unprompted; `drop` and `init` still ask, and that prompt, not a terminal
of dev-ai's, is where the operator says yes or no. Never a trust bypass, never a push.

1. The repository must be migrated: `dev-ai.json` at its root and the "Working
   with dev-ai" note in `AGENTS.md`. Missing: `dev-ai init --test-command "<the
   suite>"` prepares it once, keeping what is there, under the operator's prompt.
   Add one `--disposable "<glob>"` per thing the suite writes that git ignores
   (`*/.next/*`, `*.tsbuildinfo`), never a secret; init reports `none declared`
   on a repository without them: run it again with them. `dev-ai` not on PATH: stop and say so. Do not improvise a flow.
2. `dev-ai status`: every task, its evidence confronted with the repository, and
   the next step. Resume the task named in the arguments, or open one:
   `dev-ai start <slug> --goal "<what done means>" --paths <files it may touch>
   --author <claude|codex|opencode> --author-model <id> [--delivery merge|commit]
   [--spec <file>]`. `--author` is the harness you are,
   `--author-model` the model that writes the patch, its full id, a delegated worker's
   when one does; `start` refuses a task without it. They decide who may review, and
   a patch several models wrote is read by another harness. `--delivery merge` only when the operator said to merge, in his
   own words; otherwise `commit`, the default. Your harness picks the model with its
   own selector and rules; dev-ai holds no model list, and neither does this skill.
   A capable model already active stays: never restart a session to go down a tier. Keep the scope to the
   narrowest set that holds the change; a spec of at most 80 lines states the
   invariants the reviewer judges against. Work only inside the printed worktree.
3. Write the change, tests first when behaviour changes. A file the goal turns
   out to need: `dev-ai scope-add <path> --reason "…"`, the reason on record; a decision
   taken since `start` (the lead's, the operator's): `dev-ai scope-add --reason "<it>"`, dated, read by the reviewer.
   Then `dev-ai check` and, unless the patch is descriptive documentation only,
   `dev-ai review` (step 5), side by side: neither waits for the other, and `land`
   needs both on the same patch. The suite can outlast a shell tool's time limit: run
   both in the background and read `.dev-ai/tasks/<task>/test.log` in the main
   checkout. Checking again is always safe, and each blocker says how to
   recover; `secret_in_patch`: take the file out, never work around it.
4. Check passed and `needs_review` empty, descriptive documentation only: land
   it, `dev-ai land --task <slug> -m "<type>: <description>"`, with `--merge` under a
   `merge` mandate only, from the main checkout (a merge removes the worktree you stand in).
5. Anything else: `dev-ai review --model <id>`, the model named every time: a harness's
   default can be a free one, and a review without a name is refused. Another harness reads
   the exact patch as it stands, read-only, or yours with a model other than the author's recorded
   one.
   A `critical` or `high` finding is a claim: reproduce or refute it, then
   `dev-ai review --resolve <n> --resolution confirmed|refuted --evidence
   "<what showed it>"`. Confirmed: fix, then check and review again — one such cycle per
   request to finish, then report. Refuted: run `dev-ai review --model <id>` again; it sends
   the reviewer your evidence, and it withdraws the finding or maintains it (confirmed: fix
   it). Never merge by hand around a refuted finding.
   `unavailable`: run it again as its message says, which names every reviewer
   left; with none left, keep the task and say landing waits. On `pass`, land as
   in step 4, within the mandate: `--merge` only when `start` recorded `merge`.

Never push, never widen a scope without its reason, never change the test
command from inside the worktree, never commit to the base branch while a task
is open there. Two failures on the same hypothesis: re-examine the cause; an
environment or a parameter error never calls for a bigger model. Delegate only a
question that is independent and shortens the delay or the verification. An
explicit stop from the operator ends the task; nothing restarts it.

Report: what landed, or what waits and on whom; the model you asked for, and that the one that answered
was not observed; what you decided that nobody asked for, which the reviewer is asked first; for what the run
left, `dev-ai clean` then `--yes`, the operator's to run, and a database you made that `test_databases` misses.
