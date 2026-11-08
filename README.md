# dev-ai

Contain the work, prove the patch. A small deterministic tool for one developer
working with frontier models (Claude Code, Codex). It does not plan,
execute or route models: the harness does that. It keeps four promises. MIT licence (`LICENSE`).

| Promise | How |
|---|---|
| The work is contained | one branch and one worktree per task, under `.dev-ai/` in the checkout |
| The patch stays on target | every changed file must fall inside the task's `scope_paths` |
| The patch is tested | the host runs the repository's own test command on the exact patch |
| No change of behaviour lands unread | anything but descriptive documentation needs one review by another harness, its blocking findings confirmed or refuted with evidence |

## Quick start

You need Python 3.10 or later, git, and Claude Code, codex or opencode. The review is read by another
harness when one is installed, else by yours with another model.

```
git clone https://github.com/m3asmi/dev-ai && cd dev-ai
bash scripts/install.sh          # the command, then asks for skills, rules, tools; --dry-run changes nothing
cd ~/my-project && dev-ai init --test-command "pytest -q"   # the command that runs your tests
```

Then, in your harness, from that repository: `/dev-ai <what you want done>` (`$dev-ai` in codex, `@dev-ai` in
opencode). The skill carries the task through `start`, `check`, `review` and `land`; `docs/howto.md` walks through
one. Claude Code reads `AGENTS.md` only where no `CLAUDE.md` stands: a `CLAUDE.md` of yours starts with
`@AGENTS.md`, or the note `init` wrote goes unread. A defect in dev-ai: open a GitHub issue with the exact command
and the message it printed.

## Use

```
dev-ai init --test-command "pytest -q"   # once per repository: dev-ai.json, the AGENTS.md note, .dev-ai/ excluded
dev-ai start fix-answer --goal "make the answer right" --paths src/app.py tests/ \
    --author claude --author-model claude-opus-5-5 --delivery merge
cd <printed worktree>            # develop here, with the harness's model of your choice
dev-ai check                     # scope, tests, what needs a review — on the exact patch
dev-ai review --model gpt-6-sol  # beside the check: another harness reads the exact patch, its model named
dev-ai review --resolve 1 --resolution refuted --evidence "…"   # each blocking finding
dev-ai land -m "fix: the answer" --merge   # within the mandate recorded at start
dev-ai status                    # every task, its evidence against the repository, the next step; a last line to track use by
dev-ai scope-add src/other.py --reason "…"; dev-ai drop <task> [--destroy]   # no path: a dated decision, reviewed with
dev-ai clean [--yes]             # after merges: lists, then with --yes removes, landed worktrees and test databases
```

Every command runs under the harness's own permission rules, in the repository
where it runs (Permissions): its prompt is where the operator approves a
destruction; dev-ai asks for no terminal of its own and takes no flag as a
signature. Exit codes: `0` done, `1` blocked (the message says how to recover),
`2` the tool or git failed. Every command can be run again after any failure. A
worktree's ignored files that are not a cache are kept under `.dev-ai/tasks/<task>/kept/`. Never a push.

**Evidence is bound to the exact patch, its base and the test command that
judged it.** A check of another patch, on another base or under another
`test_command`, is stale: `status` says so, `land` refuses. If the base branch
moved, `land --merge` refuses until it is merged in the worktree and the patch
checked again; a commit landing merges nothing, and waits for no base. A review
needs no check and runs beside it: it is bound to the diff it read, its fingerprint
on a base that leaves the patch's files as they were.

**Models and mandate.** The harness chooses the author's model; `review --model`,
named every time, asks the reviewer's CLI for its own, and `--effort` (`high` unless named) for its
reasoning effort. dev-ai holds no model catalogue and observes none: the review records the model and
effort asked for and calls the one that answered
unknown. `start --delivery merge`, the operator's word and never assumed, lets
`land --merge` merge into the base and clean up; `commit`, the default, commits on the
branch only, as does a task from before mandates. Push and deployment are never in it.

## Review

`dev-ai review` is the one model call in the tool. Another harness than the author's
reads the exact patch, read-only, once, beside the check: `--author claude` is read by codex,
codex by claude, opencode by codex unless `--reviewer` names another, its `--model` named every time, a harness's default being nobody's choice; the author's
own harness only with a model other than the recorded `--author-model`, which is refused everywhere. With no
`--reviewer` and the other harness's CLI not on `PATH`, the author's own harness reviews, under that same rule.
It answers in JSON, each finding with a file, a line, the failure scenario and
the evidence, and `dev-ai` computes the verdict: a `critical` or `high` finding
is `pending` until `review --resolve` records it `confirmed` (the patch fails;
fix, check, review again) or `refuted` with evidence; a run of the same patch never
erases a pending or confirmed finding, and a refuted one goes back to a reviewer: the next
`dev-ai review` sends it the patch and the author's evidence, in one call, and it answers
`maintained` (now confirmed) or `withdrawn`; any other answer leaves it open. Nobody types an
approval. A timeout, a provider error or an answer that is not the JSON
asked for is `unavailable`, never `pass`, and its message names every reviewer left to run
the command again with. The reviewer runs on its harness's login, never on `ANTHROPIC_API_KEY`.
The output is kept in `review.log`; `start --spec <file>` records up to 80 lines of invariants.

## For the agent

`dev-ai` instructs nobody; the repository does. The note is the `Working with
dev-ai` section of this repository's own `AGENTS.md`, live there rather than
quoted here: `dev-ai init` copies its bullets into the `AGENTS.md` of a repository
that uses dev-ai. One copy, and the tool obeys the note it hands out.

## Permissions

The flow runs unprompted, except what destroys (the owner, 2026-09-21), for `status`, `start`,
`check`, `scope-add`, `review` and `land`; `drop`, `clean` and `init` still ask, unless a broader rule of the
operator's own allows them (`Bash(dev-ai:*)`, an earlier release's, is his to remove). Claude Code: the
operator's user settings, `~/.claude/settings.json`, where the installer adds them after his own, none changed,
a file of another shape left as it is and said, a write that fails ending the install: `"permissions": {"allow": ["Bash(dev-ai check *)", …]}` and
`"sandbox": {"excludedCommands": ["dev-ai *"]}`, so the reviewer reaches its login and `drop` is not a
sandboxed command that `autoAllowBashIfSandboxed` runs unasked; `dev-ai` without `*` matches the bare command
only. codex: `~/.codex/rules/dev-ai.rules`, a copy of `scripts/dev-ai.rules`, read in every project where a
project's own rules wait for codex to trust it: the six verbs `allow`, outside its sandbox, and `drop`, `clean`,
`init` `prompt`; its strictest matching rule wins, so a `forbidden` of his stands. opencode, which has no sandbox
and runs any command no rule asks about: `"dev-ai drop *": "ask"`, `clean` and `init` alike, added to
`~/.config/opencode/opencode.json` right after his last rule that allows the verb, as its last matching rule wins, so
every later rule of his still wins; none where his rules ask or deny it, his own key for it kept, an `opencode.jsonc` or another shape left as it is and said. `init` writes no
rule in a repository: Claude's trust prompt warned on every one that held them (the owner, 2026-11-04), and codex
read none it did not trust. Whatever the harness, run each `dev-ai` command bare: behind `cd …&&`, `env`, a
redirect or `&`, no rule matches it, and Claude Code's sandbox keeps a call with a `cd` or a redirect.

## Install

`bash scripts/install.sh` installs; `--dry-run` prints what it would change and changes nothing. It puts a
second worktree of this repository at the tip of `main`, links it onto `PATH` as `dev-ai`, copies `docs/skill.md`
where Claude Code, codex (`~/.agents/skills`, its docs) and opencode (`~/.config/opencode/skills`) read skills:
`/dev-ai`, `$dev-ai` in codex, `@dev-ai` in opencode, is the one entry point; beside it `skills/frame-task`, which
frames a task before `start`. It deletes nothing: what an earlier release wrote stays where it is,
the operator's to remove. At the command's path it replaces nothing either: whatever stands there, but the link
an install wrote, is refused, his to move; a skill or rules file of his that is a link is left, said. It adds each harness's rules (Permissions). It names rtk and context-mode when absent,
with their own install command, and runs neither. The skill for each harness found, each one's rules and the context tools
are each asked on stdin, `[Y/n]`: no answer keeps yes, and `--yes` asks nothing. Daily use never runs from the checkout
being edited: a half-edited `dev-ai` would judge real patches.

To update a machine: `git pull`, then run the installer again. What landed on `main` is what
runs; no tag to make or push (tags made before 2026-10-14 stay as markers).

## Configure

`dev-ai.json` at the repository root, read from the **main checkout**, never from
the task's worktree: a patch cannot change the test command that judges it. The test
files and their configuration are part of the patch, and reviewed with it. `dev-ai init
--test-command "…"` writes it; a dev-pipeline `dp-project.json` is not read.

| Key | Meaning |
|---|---|
| `test_command` | required; one command, run with the worktree as working directory, `DEV_AI_WORKTREE` and `DEV_AI_TASK` exported. Several suites and any scanner the repository wants are chained here: `"unit && e2e && semgrep --config auto --error ."` (gitleaks, trivy alike) — `dev-ai` runs no scanner itself |
| `test_timeout` | seconds for that whole command, default 1800 |
| `review_timeout` | seconds, default 900 |
| `base` | branch tasks start from; default: the main checkout's current branch |
| `disposable` | globs over `<worktree>/<path>` of what the suite writes and git ignores (`["*/.next/*", "*.tsbuildinfo"]`), which `drop`, `land` and `clean` may delete beside the usual caches; every other ignored file is kept. Written by `init --disposable`, from the agent that read the repository |
| `test_databases` | a regex of the names of the databases the test command leaves, e.g. `^oai_dp_(ci\|e2e)_`; `dev-ai clean --yes` drops those no session uses; unset, it touches none |

## What is recorded, and what is next

Under `.dev-ai/` in the main checkout, excluded from git locally: one directory
per task, and `log.jsonl`, one row per command with its time, outcome, tool
version and, when blocked, the kind of blocker. Preparation, run and waiting
times fall out of those rows, and so does which check ever fired. Formats,
invariants and the threat model: `docs/design.md`. The budget, enforced as tests:
`AGENTS.md`. Tracking your own use, and what is not planned: `docs/roadmap.md`. Measures name
repositories by role: *the bench* is the Odoo addons repository dev-ai was
measured on first; the others are a localisation repository and a Next.js site.
